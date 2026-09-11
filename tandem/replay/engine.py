"""Effect-aware capability execution engine implementing the 14-step commit protocol."""

from typing import Any, Dict, Optional

from playwright.sync_api import Page
from sqlalchemy.orm import Session

from tandem.domain.capability import CapabilityDefinition
from tandem.domain.effects import EffectClass
from tandem.domain.outcomes import ExecutionOutcome, OutcomeCategory, OutcomeCode
from tandem.ledger.repository import LedgerRepository
from tandem.policy.engine import PolicyEngine
from tandem.replay.executor import DeterministicExecutor, render_template
from tandem.replay.precheck import execute_precheck
from tandem.replay.reconciliation import reconcile_commit_execution
from tandem.surfaces.base import SurfaceOverlay


class EffectEngine:
    """Orchestrates effect-aware replay with prechecks, scoped guards, and reconciliation."""

    def __init__(self, session: Session, page: Page, overlay: Optional[SurfaceOverlay] = None):
        self.session = session
        self.page = page
        self.overlay = overlay
        self.repo = LedgerRepository(session)
        self.executor = DeterministicExecutor(page=page, overlay=overlay)

    def execute_capability(
        self, capability: CapabilityDefinition, inputs: Dict[str, Any]
    ) -> ExecutionOutcome:
        """Execute a capability according to its declared effect class."""
        case_id = inputs.get("case_id", "UNKNOWN_CASE")
        member_id = inputs.get("member_id", "UNKNOWN_MEMBER")
        amount = float(inputs.get("amount", 0.0))

        # Ensure case exists in ledger
        self.repo.create_or_get_case(case_id=case_id, member_id=member_id, amount=amount)

        # -------------------------------------------------------------------
        # 1. Policy Evaluation
        # -------------------------------------------------------------------
        policy_failure = PolicyEngine.evaluate(capability, inputs)
        if policy_failure:
            self.repo.record_event(
                case_id=case_id,
                event_type="POLICY_DENIED",
                step_name=capability.id,
                payload={"message": policy_failure.message},
            )
            return policy_failure

        # -------------------------------------------------------------------
        # 2. Idempotency Key Computation
        # -------------------------------------------------------------------
        idempotency_key = None
        if capability.effect.idempotency_key:
            idempotency_key = render_template(capability.effect.idempotency_key, {"input": inputs})

        # -------------------------------------------------------------------
        # 3. Precheck (Prevents double execution before touching the browser)
        # -------------------------------------------------------------------
        if capability.effect.effect_class == EffectClass.COMMIT:
            precheck_outcome = execute_precheck(capability, inputs)
            if precheck_outcome and precheck_outcome.code == OutcomeCode.ALREADY_APPLIED:
                # Effect already exists! Record to ledger and return immediately without firing browser steps.
                self.repo.record_event(
                    case_id=case_id,
                    event_type="PRECHECK_ALREADY_APPLIED",
                    step_name=capability.id,
                    payload={
                        "memo": precheck_outcome.audit_ref,
                        "message": precheck_outcome.message,
                    },
                )
                exec_record = self.repo.start_execution(
                    case_id=case_id,
                    capability_id=capability.id,
                    capability_version=capability.version,
                    effect_class=capability.effect.effect_class.value,
                    idempotency_key=idempotency_key,
                )
                self.repo.complete_execution(
                    execution_id=exec_record.id,
                    status=OutcomeCode.ALREADY_APPLIED.value,
                    audit_ref=precheck_outcome.audit_ref,
                    money_moved=False,
                )
                self.session.commit()
                return precheck_outcome

        # -------------------------------------------------------------------
        # 4. Acquire Single-Owner Lease & Write Staged Intent
        # -------------------------------------------------------------------
        self.repo.acquire_lease(case_id=case_id, owner="AUTOMATION")
        if idempotency_key:
            self.repo.stage_intent(
                case_id=case_id,
                idempotency_key=idempotency_key,
                capability_id=capability.id,
            )

        exec_record = self.repo.start_execution(
            case_id=case_id,
            capability_id=capability.id,
            capability_version=capability.version,
            effect_class=capability.effect.effect_class.value,
            idempotency_key=idempotency_key,
            expected_entity=member_id,
            expected_amount=amount,
        )
        self.session.commit()

        # -------------------------------------------------------------------
        # 5. Deterministic Browser Replay (Includes Control-Scoped Guards)
        # -------------------------------------------------------------------
        try:
            outcome = self.executor.execute(capability=capability, inputs=inputs)
        except Exception as exc:
            # Network drop or browser crash around commit -> invoke reconciliation!
            if capability.effect.effect_class == EffectClass.COMMIT:
                outcome = reconcile_commit_execution(
                    capability=capability, inputs=inputs, error_message=str(exc)
                )
            else:
                outcome = ExecutionOutcome(
                    category=OutcomeCategory.RECOVERABLE_FAILURE,
                    code=OutcomeCode.NETWORK_TIMEOUT,
                    message=f"Browser execution failed: {exc}",
                    money_moved=False,
                )

        # -------------------------------------------------------------------
        # 6. Post-Action Settlement, Audit Persist & Lease Release
        # -------------------------------------------------------------------
        self.repo.complete_execution(
            execution_id=exec_record.id,
            status=outcome.code.value,
            observed_entity=inputs.get("member_id"),
            observed_amount=amount if outcome.money_moved else None,
            audit_ref=outcome.audit_ref,
            money_moved=outcome.money_moved,
            failure_category=outcome.category.value if not outcome.is_success else None,
        )

        if outcome.money_moved:
            self.repo.update_case_status(
                case_id=case_id,
                status="PROVISIONAL_CREDIT_POSTED",
                money_moved=True,
            )
            self.repo.record_event(
                case_id=case_id,
                event_type="MONEY_MOVED",
                step_name=capability.id,
                payload={"amount": amount, "ref": outcome.audit_ref},
            )

        if outcome.category == OutcomeCategory.UNCERTAIN_EFFECT:
            self.repo.update_case_status(case_id=case_id, status="UNCERTAIN_EFFECT")
            self.repo.record_event(
                case_id=case_id,
                event_type="UNCERTAIN_EFFECT_ESCALATION",
                step_name=capability.id,
                payload={"message": outcome.message},
            )

        elif outcome.category == OutcomeCategory.HARD_FAILURE:
            self.repo.update_case_status(case_id=case_id, status="FAILED")
            self.repo.record_event(
                case_id=case_id,
                event_type="HARD_FAILURE",
                step_name=capability.id,
                payload={"code": outcome.code.value, "message": outcome.message},
            )

        if idempotency_key and outcome.is_success:
            self.repo.mark_intent_committed(idempotency_key)

        self.repo.release_lease(case_id=case_id)
        self.session.commit()

        return outcome
