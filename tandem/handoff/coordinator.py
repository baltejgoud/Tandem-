"""Human Handoff Coordinator.

Manages single-owner mutual-exclusion lease transitions between AUTOMATION and HUMAN
operators, compliance review interstitial handling, operator sign-off, and safe resumption.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from playwright.sync_api import Page
from sqlalchemy.orm import Session

from tandem.domain.errors import LeaseConflictError
from tandem.ledger.models import LeaseRecord
from tandem.ledger.repository import LedgerRepository
from tandem.workflow.state_machine import RegEState


class HandoffCoordinator:
    """Coordinates operator takeover, single-owner leases, and automated resumption."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = LedgerRepository(session)

    def initiate_handoff(
        self,
        case_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Release automation lease and place case into NEEDS_HUMAN state."""
        self.repo.release_lease(case_id)
        self.repo.update_case_status(case_id, status=RegEState.NEEDS_HUMAN.value)
        self.repo.record_event(
            case_id=case_id,
            event_type="HUMAN_HANDOFF_INITIATED",
            step_name="handoff_coordinator",
            payload={"reason": reason, "details": details or {}},
        )
        self.session.commit()
        return {
            "case_id": case_id,
            "status": RegEState.NEEDS_HUMAN.value,
            "reason": reason,
            "ticket_id": f"TICKET-{case_id}",
        }

    def claim_operator_lease(self, case_id: str, operator_id: str) -> LeaseRecord:
        """Enforce single-owner lease rule before an operator can act on a case."""
        current_lease = self.repo.get_lease(case_id)
        if current_lease and not current_lease.released_at:
            if current_lease.owner == "AUTOMATION":
                raise LeaseConflictError(
                    f"Case {case_id} lease currently held by AUTOMATION. "
                    f"Automation must yield lease before operator can claim."
                )
            elif current_lease.owner != operator_id:
                raise LeaseConflictError(
                    f"Case {case_id} lease already held by operator '{current_lease.owner}'. "
                    f"Single-owner invariant prevents concurrent operator claims."
                )

        lease = self.repo.acquire_lease(case_id=case_id, owner=operator_id)
        self.repo.record_event(
            case_id=case_id,
            event_type="OPERATOR_LEASE_ACQUIRED",
            step_name="handoff_coordinator",
            payload={"operator_id": operator_id},
        )
        self.session.commit()
        return lease

    def operator_clear_compliance(
        self,
        case_id: str,
        operator_id: str,
        page: Page,
        frame_selector: str = "#core_workspace_frame",
    ) -> Dict[str, Any]:
        """Operator signs off compliance interstitial on the active browser session."""
        lease = self.repo.get_lease(case_id)
        if not lease or lease.released_at or lease.owner != operator_id:
            raise LeaseConflictError(
                f"Operator '{operator_id}' does not hold active lease for case {case_id}."
            )

        frame = page.frame_locator(frame_selector)
        signoff_btn = frame.locator("button.operator-signoff-btn, .operator-signoff-btn")
        signoff_btn.wait_for(state="visible", timeout=5000)
        signoff_btn.click()

        # Wait for iframe to process clear_compliance and navigate back to credit entry form
        try:
            frame.locator("#credit_action_container").wait_for(state="visible", timeout=5000)
        except Exception:
            pass

        # Record handoff audit entry
        self.repo.record_handoff(
            case_id=case_id,
            reason="COMPLIANCE_INTERSTITIAL",
            operator_id=operator_id,
            action_taken="ACKNOWLEDGED_COMPLIANCE_AND_SIGNOFF",
        )
        self.repo.record_event(
            case_id=case_id,
            event_type="OPERATOR_COMPLIANCE_CLEARED",
            step_name="handoff_coordinator",
            payload={"operator_id": operator_id},
        )

        # Release operator lease and yield back to AUTOMATION
        self.repo.release_lease(case_id)
        self.repo.acquire_lease(case_id=case_id, owner="AUTOMATION")
        self.session.commit()

        return {
            "case_id": case_id,
            "status": "COMPLIANCE_CLEARED",
            "operator_id": operator_id,
            "next_owner": "AUTOMATION",
        }
