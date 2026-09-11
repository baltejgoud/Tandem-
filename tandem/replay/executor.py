"""Deterministic capability execution engine using Playwright and Surface abstraction."""

from typing import Any, Dict, Optional

from playwright.sync_api import Page

from tandem.domain.capability import CapabilityDefinition, StepAction
from tandem.domain.effects import EffectClass
from tandem.domain.errors import (
    AmountMismatchError,
    ComplianceInterstitialError,
    EntityBindingMismatchError,
    PageDriftError,
    SessionExpiredError,
)
from tandem.domain.outcomes import ExecutionOutcome, OutcomeCategory, OutcomeCode
from tandem.policy.telemetry import llm_tracker
from tandem.replay.guards import verify_control_scoped_guard
from tandem.surfaces.base import SurfaceOverlay
from tandem.surfaces.playwright_surface import PlaywrightSurface


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Simple template renderer resolving expressions like {{input.member_id}}."""
    result = template_str
    for key, val in context.get("input", {}).items():
        result = result.replace(f"{{{{input.{key}}}}}", str(val))
        result = result.replace(f"{{{{{key}}}}}", str(val))
    return result


class DeterministicExecutor:
    """Executes a compiled capability artifact deterministically using Playwright with 0 LLM calls."""

    def __init__(self, page: Page, overlay: Optional[SurfaceOverlay] = None):
        self.page = page
        self.surface = PlaywrightSurface(page)
        self.overlay = overlay

    def execute(self, capability: CapabilityDefinition, inputs: Dict[str, Any]) -> ExecutionOutcome:
        """Execute capability steps. Replay must perform ZERO LLM calls."""
        # Baseline LLM count check
        llm_count_before = llm_tracker.call_count

        context = {"input": inputs}
        frame_selector = "#core_workspace_frame"  # Standard hostile frame if applicable

        try:
            # Check for session expiration early if page loaded
            if "SESSION EXPIRED" in self.page.content():
                raise SessionExpiredError("Target system session has timed out")

            for step in capability.steps:
                # Check for compliance review interstitial
                try:
                    ctx = self.surface._get_context(frame_selector)
                    if (
                        ctx.locator("#compliance_interstitial_panel").count() > 0
                        or "COMPLIANCE INTERSTITIAL REVIEW REQUIRED" in (self.page.content() or "")
                    ):
                        raise ComplianceInterstitialError(
                            "Compliance review interstitial encountered; manual operator sign-off required"
                        )
                except ComplianceInterstitialError:
                    raise
                except Exception:
                    pass

                # 1. Container-scoped guard check immediately prior to or during commit actions
                if step.action in {StepAction.ASSERT_CONTAINER, StepAction.SUBMIT}:
                    verify_control_scoped_guard(
                        capability=capability,
                        inputs=inputs,
                        surface=self.surface,
                        frame_selector=step.frame_selector or frame_selector,
                        overlay=self.overlay,
                        control_candidates=(
                            step.locator_candidates if step.action == StepAction.SUBMIT else None
                        ),
                        semantic_target=step.semantic_target,
                    )

                # 2. Execute step action
                if step.action == StepAction.NAVIGATE:
                    url = render_template(step.semantic_target, context)
                    self.surface.navigate(url)

                elif step.action == StepAction.FILL:
                    value = (
                        render_template(step.input_value_template, context)
                        if step.input_value_template
                        else ""
                    )
                    effective_frame = step.frame_selector or frame_selector
                    self.surface.resolve_and_fill(
                        semantic_target=step.semantic_target,
                        candidates=step.locator_candidates,
                        value=value,
                        frame_selector=effective_frame,
                        overlay=self.overlay,
                    )

                elif step.action in {StepAction.CLICK, StepAction.SUBMIT}:
                    effective_frame = step.frame_selector or frame_selector
                    self.surface.resolve_and_click(
                        semantic_target=step.semantic_target,
                        candidates=step.locator_candidates,
                        frame_selector=effective_frame,
                        overlay=self.overlay,
                    )

            # Invariant check: Assert ZERO LLM calls took place during replay
            llm_calls_made = llm_tracker.call_count - llm_count_before
            if llm_calls_made > 0:
                raise RuntimeError(
                    f"CRITICAL SAFETY VIOLATION: Replay engine invoked {llm_calls_made} LLM calls! "
                    f"Replay must be 100% deterministic."
                )

            context_el = self.surface._get_context(frame_selector)
            memo_code = None
            try:
                memo_el = context_el.locator("#receipt_memo_code, .result-memo-code").first
                if memo_el.is_visible(timeout=2000):
                    memo_code = memo_el.text_content().strip()
            except Exception:
                pass

            money_moved = False
            try:
                money_el = context_el.locator("#receipt_money_moved").first
                if money_el.is_visible(timeout=1000):
                    money_moved = "MONEY_MOVED=TRUE" in (money_el.text_content() or "")
            except Exception:
                pass

            # Every COMMIT requires independent target confirmation. DOM receipts
            # are evidence, but never sufficient proof of an external effect.
            if capability.effect.effect_class == EffectClass.COMMIT:
                from tandem.replay.postcheck import execute_postcheck

                postcheck = execute_postcheck(capability, inputs)
                if not postcheck.is_success:
                    return postcheck
                memo_code = postcheck.audit_ref
                money_moved = postcheck.money_moved

            return ExecutionOutcome(
                category=OutcomeCategory.SUCCESS,
                code=OutcomeCode.COMPLETED,
                message=f"Capability '{capability.id}' replayed successfully with 0 LLM calls",
                details={
                    "memo_code": memo_code,
                    "money_moved": money_moved,
                    "drift_events": self.surface.drift_events,
                },
                money_moved=money_moved,
                audit_ref=memo_code,
            )

        except EntityBindingMismatchError as e:
            return ExecutionOutcome(
                category=OutcomeCategory.HARD_FAILURE,
                code=OutcomeCode.ENTITY_BINDING_MISMATCH,
                message=str(e),
                details={"inputs": inputs},
                money_moved=False,
            )

        except AmountMismatchError as e:
            return ExecutionOutcome(
                category=OutcomeCategory.HARD_FAILURE,
                code=OutcomeCode.AMOUNT_MISMATCH,
                message=str(e),
                details={"inputs": inputs},
                money_moved=False,
            )

        except PageDriftError as e:
            return ExecutionOutcome(
                category=OutcomeCategory.RECOVERABLE_FAILURE,
                code=OutcomeCode.PAGE_DRIFT,
                message=str(e),
                details={"drift_events": self.surface.drift_events},
                money_moved=False,
            )

        except ComplianceInterstitialError as e:
            return ExecutionOutcome(
                category=OutcomeCategory.NEEDS_HUMAN,
                code=OutcomeCode.COMPLIANCE_INTERSTITIAL,
                message=str(e),
                details={"interstitial_type": "REG_E_COMPLIANCE_REVIEW"},
                money_moved=False,
            )

        except SessionExpiredError as e:
            return ExecutionOutcome(
                category=OutcomeCategory.RECOVERABLE_FAILURE,
                code=OutcomeCode.SESSION_EXPIRED,
                message=str(e),
                money_moved=False,
            )

        except Exception as e:
            return ExecutionOutcome(
                category=OutcomeCategory.HARD_FAILURE,
                code=OutcomeCode.POLICY_VIOLATION,
                message=f"Replay failed unexpectedly: {e}",
                money_moved=False,
            )
