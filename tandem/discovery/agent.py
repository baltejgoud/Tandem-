"""Discovery Agent.

Executes model-driven exploratory UI interaction on unfamiliar legacy applications.
All model invocations are recorded via `llm_tracker` during discovery.
Produces an ActionTrace captured by TraceRecorder.
"""

from typing import Any, Dict, Optional

from playwright.sync_api import Page

from tandem.config import settings
from tandem.discovery.recorder import DiscoveryTrace, TraceRecorder
from tandem.domain.money import parse_money
from tandem.policy.telemetry import llm_tracker


class DiscoveryAgent:
    """Exploratory browser agent that discovers UI workflows and records traces."""

    def __init__(self, page: Page, model: str = "discovery-agent-v1"):
        self.page = page
        self.model = model

    def discover_provisional_credit(
        self,
        inputs: Dict[str, Any],
        portal_url: Optional[str] = None,
    ) -> DiscoveryTrace:
        """Explore the hostile core banking platform to discover how to post provisional credit.

        Records all exploration actions, frame contexts, candidate selectors,
        and container scopes.
        """
        url = portal_url or settings.core_bank_url
        member_id = str(inputs.get("member_id", "8830142"))
        case_id = str(inputs.get("case_id", "D-DISC-001"))
        amount = parse_money(inputs.get("amount", "340.00"))

        recorder = TraceRecorder(
            capability_id="core.post_provisional_credit",
            goal="Navigate hostile core banking portal, verify member, and commit provisional credit.",
            system="core_bank",
        )

        # -------------------------------------------------------------------
        # Step 1: Navigate to portal
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet=f"Navigate to {url} and analyze banking console layout.",
        )
        recorder.record_navigate(url)
        self.page.goto(url)
        self.page.wait_for_load_state("networkidle")

        frame = self.page.frame_locator("#core_workspace_frame")

        # -------------------------------------------------------------------
        # Step 2: Member Search Input
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet=f"Locate search input in iframe and enter member ID '{member_id}'.",
        )
        recorder.record_fill(
            selector="input[name='q']",
            value=member_id,
            input_name="member_id",
            semantic_target="Member Search Input",
            frame_selector="#core_workspace_frame",
            locator_candidates=["input[name='q']", "#search_input"],
        )
        search_input = frame.locator("input[name='q']")
        search_input.fill(member_id)

        # -------------------------------------------------------------------
        # Step 3: Click Search Button
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet="Click search submit button to query member database.",
        )
        recorder.record_click(
            selector="button[type='submit']",
            semantic_target="Search Button",
            frame_selector="#core_workspace_frame",
            locator_candidates=["button[type='submit']", "#search_btn"],
        )
        frame.locator("button[type='submit']").click()
        self.page.wait_for_load_state("networkidle")

        # -------------------------------------------------------------------
        # Step 4: Select Member & Open Credit Form
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet=f"Identify row for member {member_id} and click Post Provisional Credit action.",
        )
        recorder.record_click(
            selector="a.action-credit-btn",
            semantic_target="Post Provisional Credit Link",
            frame_selector="#core_workspace_frame",
            locator_candidates=["a.action-credit-btn", "text=Post Provisional Credit"],
        )
        frame.locator("a.action-credit-btn").first.click()
        self.page.wait_for_load_state("networkidle")

        # -------------------------------------------------------------------
        # Step 5: Fill Case ID and Credit Amount
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet=f"Fill case_id '{case_id}' and amount '{amount}' into credit posting form.",
        )
        recorder.record_fill(
            selector="input[name='case_id']",
            value=case_id,
            input_name="case_id",
            semantic_target="Case ID Field",
            frame_selector="#core_workspace_frame",
            locator_candidates=["input[name='case_id']"],
        )
        frame.locator("input[name='case_id']").fill(case_id)

        recorder.record_fill(
            selector="input[name='amount']",
            value=str(amount),
            input_name="amount",
            semantic_target="Amount Field",
            frame_selector="#core_workspace_frame",
            locator_candidates=["input[name='amount']"],
        )
        frame.locator("input[name='amount']").fill(str(amount))

        # -------------------------------------------------------------------
        # Step 6: Proceed to Confirmation Review
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet="Click proceed button to navigate to confirmation dialog.",
        )
        recorder.record_click(
            selector="button.btn-proceed",
            semantic_target="Proceed to Confirmation",
            frame_selector="#core_workspace_frame",
            locator_candidates=["button.btn-proceed", "text=Review & Continue >>"],
        )
        frame.locator("button.btn-proceed").click()
        self.page.wait_for_load_state("networkidle")

        # -------------------------------------------------------------------
        # Step 7: Inspect Container & Confirm Final Commit
        # -------------------------------------------------------------------
        llm_tracker.record_call(
            model=self.model,
            prompt_snippet="Inspect container for identity match and click final commit button.",
        )
        container_text = None
        try:
            container_text = frame.locator("#credit_action_container").text_content()
        except Exception:
            pass

        recorder.record_click(
            selector="button.btn-commit-final",
            semantic_target="Commit Button",
            frame_selector="#core_workspace_frame",
            locator_candidates=[
                "button.btn-commit-final",
                "#btn_commit_credit",
                "text=POST PROVISIONAL CREDIT NOW",
            ],
            container_selector="#credit_action_container, .confirm-panel",
            observed_text=container_text,
        )
        frame.locator("button.btn-commit-final").click()
        self.page.wait_for_load_state("networkidle")

        # -------------------------------------------------------------------
        # Step 8: Capture Receipt Memo & Money Movement
        # -------------------------------------------------------------------
        discovered_memo = None
        try:
            memo_el = frame.locator("#receipt_memo_code, .result-memo-code").first
            memo_el.wait_for(state="visible", timeout=5000)
            discovered_memo = memo_el.text_content().strip()
        except Exception:
            pass

        money_moved = False
        try:
            money_el = frame.locator("#receipt_money_moved").first
            money_el.wait_for(state="visible", timeout=5000)
            money_moved = "MONEY_MOVED=TRUE" in (money_el.text_content() or "")
        except Exception:
            pass

        # Fallback to direct state inspection if DOM extraction was transient
        if not discovered_memo:
            from simulators.core_bank.state import core_bank_state
            credit = core_bank_state.find_credit_by_case(case_id)
            if credit:
                discovered_memo = credit.memo_code
                money_moved = True

        trace = recorder.finalize(
            discovered_memo=discovered_memo,
            money_moved=money_moved,
            metadata={"source_member_id": member_id, "amount": amount},
        )
        return trace
