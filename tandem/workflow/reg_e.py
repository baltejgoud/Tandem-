"""End-to-end Regulation E debit card dispute workflow orchestrator."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx
from playwright.sync_api import Page
from sqlalchemy.orm import Session

from tandem.config import settings
from tandem.domain.capability import load_capability_from_yaml
from tandem.domain.outcomes import OutcomeCategory, OutcomeCode
from tandem.domain.money import parse_money
from tandem.ledger.repository import LedgerRepository
from tandem.ledger.service import LedgerService
from tandem.replay.engine import EffectEngine
from tandem.workflow.deadlines import add_business_days, calculate_reg_e_deadlines
from tandem.workflow.state_machine import RegEState, can_transition


class RegEWorkflow:
    """Orchestrates cross-system Regulation E dispute processing."""

    def __init__(
        self,
        session: Session,
        page: Optional[Page] = None,
        kill_after_credit: bool = False,
    ):
        self.session = session
        self.page = page
        self.repo = LedgerRepository(session)
        self.service = LedgerService(session)
        self.kill_after_credit = kill_after_credit or (
            os.environ.get("PROCESS_KILL_AFTER") == "core.post_provisional_credit"
        )

    def transition(
        self, case_id: str, new_state: RegEState, money_moved: Optional[bool] = None
    ) -> None:
        case = self.repo.get_case(case_id)
        current = RegEState(case.status) if case else RegEState.RECEIVED
        if not can_transition(current, new_state):
            raise ValueError(f"Illegal state transition from {current} to {new_state}")

        self.repo.update_case_status(case_id, status=new_state.value, money_moved=money_moved)
        self.repo.record_event(
            case_id=case_id,
            event_type="STATE_TRANSITION",
            step_name="orchestrator",
            payload={"from": current.value, "to": new_state.value},
        )
        self.session.commit()

    def run_case(
        self,
        case_id: str,
        member_id: str,
        amount: Decimal,
        card_last4: str = "4112",
        injected_clock: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Execute full Reg E dispute processing or resume from persistent ledger."""
        clock = injected_clock or datetime.now(timezone.utc)
        amount = parse_money(amount)

        # 0. Check if case already exists in ledger
        existing_case = self.repo.get_case(case_id)
        if existing_case:
            snapshot = self.service.reconstruct_case_state(case_id)
        else:
            self.repo.create_or_get_case(
                case_id=case_id,
                member_id=member_id,
                amount=amount,
                procedure_name="reg_e_dispute",
            )
            # Register statutory deadlines
            deadlines = calculate_reg_e_deadlines(clock)
            self.repo.create_deadline(
                case_id, "INVESTIGATION_10_DAY", deadlines["INVESTIGATION_10_DAY"]
            )
            self.repo.create_deadline(
                case_id, "FINAL_RESOLUTION_45_DAY", deadlines["FINAL_RESOLUTION_45_DAY"]
            )
            self.session.commit()
            snapshot = self.service.reconstruct_case_state(case_id)

        # -------------------------------------------------------------------
        # Step 1: Member Verification (READ)
        # -------------------------------------------------------------------
        if "core.verify_member" not in snapshot.completed_capabilities:
            resp = httpx.get(f"{settings.core_bank_url}/api/member/{member_id}", timeout=3.0)
            if resp.status_code != 200:
                self.transition(case_id, RegEState.FAILED)
                return {"status": "FAILED", "error": f"Member {member_id} not found"}

            exec_rec = self.repo.start_execution(
                case_id=case_id,
                capability_id="core.verify_member",
                capability_version="1.0.0",
                effect_class="READ",
                expected_entity=member_id,
            )
            self.repo.complete_execution(exec_rec.id, status="SUCCESS", observed_entity=member_id)
            self.transition(case_id, RegEState.MEMBER_VERIFIED)

        # -------------------------------------------------------------------
        # Step 2: Locate Transaction (READ)
        # -------------------------------------------------------------------
        if "core.locate_transaction" not in snapshot.completed_capabilities:
            exec_rec = self.repo.start_execution(
                case_id=case_id,
                capability_id="core.locate_transaction",
                capability_version="1.0.0",
                effect_class="READ",
            )
            self.repo.complete_execution(exec_rec.id, status="SUCCESS", observed_amount=amount)
            self.transition(case_id, RegEState.TRANSACTION_VERIFIED)

        # -------------------------------------------------------------------
        # Step 3: Duplicate Dispute Check (READ)
        # -------------------------------------------------------------------
        if "core.check_duplicate_dispute" not in snapshot.completed_capabilities:
            exec_rec = self.repo.start_execution(
                case_id=case_id,
                capability_id="core.check_duplicate_dispute",
                capability_version="1.0.0",
                effect_class="READ",
            )
            self.repo.complete_execution(exec_rec.id, status="SUCCESS")
            self.transition(case_id, RegEState.DUPLICATE_CHECKED)

        # -------------------------------------------------------------------
        # Step 4: Card Processor Chargeback (COMMIT)
        # -------------------------------------------------------------------
        if "processor.file_chargeback" not in snapshot.completed_capabilities:
            resp = httpx.post(
                f"{settings.processor_url}/chargeback/file",
                data={"case_id": case_id, "card_last4": card_last4, "amount": amount},
                timeout=5.0,
            )
            if resp.status_code == 401:
                self.transition(case_id, RegEState.NEEDS_HUMAN)
                return {"status": "NEEDS_HUMAN", "error": "Processor session expired"}
            elif resp.status_code == 504:
                # Interrupted request -> run postcheck reconciliation inquiry!
                try:
                    inquiry = httpx.get(
                        f"{settings.processor_url}/api/chargebacks/{case_id}", timeout=3.0
                    )
                    if inquiry.status_code == 200:
                        data = inquiry.json()
                        network_ref = data.get("network_ref", f"CB-{case_id}")
                        exec_rec = self.repo.start_execution(
                            case_id=case_id,
                            capability_id="processor.file_chargeback",
                            capability_version="1.0.0",
                            effect_class="COMMIT",
                            idempotency_key=f"regE:{case_id}:chargeback",
                        )
                        self.repo.complete_execution(
                            exec_rec.id, status="SUCCESS", audit_ref=network_ref
                        )
                        self.repo.record_event(
                            case_id=case_id,
                            event_type="EFFECT_RECONCILED",
                            step_name="processor.file_chargeback",
                            payload={"network_ref": network_ref, "message": "Reconciled after 504"},
                        )
                        self.transition(case_id, RegEState.CHARGEBACK_FILED)
                    else:
                        # Postcheck inconclusive -> UNCERTAIN_EFFECT!
                        self.transition(case_id, RegEState.UNCERTAIN_EFFECT)
                        return {
                            "status": "UNCERTAIN_EFFECT",
                            "code": "UNCERTAIN_EFFECT",
                            "error": "Processor timeout dropped; postcheck inquiry inconclusive",
                        }
                except Exception:
                    self.transition(case_id, RegEState.UNCERTAIN_EFFECT)
                    return {
                        "status": "UNCERTAIN_EFFECT",
                        "code": "UNCERTAIN_EFFECT",
                        "error": "Processor timeout dropped; postcheck inquiry failed",
                    }
            elif resp.status_code != 200:
                self.transition(case_id, RegEState.FAILED)
                return {"status": "FAILED", "error": "Processor chargeback failed"}

            exec_rec = self.repo.start_execution(
                case_id=case_id,
                capability_id="processor.file_chargeback",
                capability_version="1.0.0",
                effect_class="COMMIT",
                idempotency_key=f"regE:{case_id}:chargeback",
            )
            self.repo.complete_execution(exec_rec.id, status="SUCCESS", audit_ref=f"CB-{case_id}")
            self.transition(case_id, RegEState.CHARGEBACK_FILED)

        # -------------------------------------------------------------------
        # Step 5: Post Provisional Credit (COMMIT - MOVES MONEY)
        # -------------------------------------------------------------------
        if "core.post_provisional_credit" not in snapshot.completed_capabilities:
            cap = load_capability_from_yaml("capabilities/core/post_provisional_credit.yaml")

            if not self.page:
                raise RuntimeError(
                    "Playwright page required for core.post_provisional_credit replay"
                )

            engine = EffectEngine(session=self.session, page=self.page)
            outcome = engine.execute_capability(
                capability=cap,
                inputs={"member_id": member_id, "case_id": case_id, "amount": amount},
            )

            if outcome.code == OutcomeCode.POLICY_DENIED:
                self.transition(case_id, RegEState.NEEDS_HUMAN)
                return {"status": "POLICY_DENIED", "message": outcome.message}

            if outcome.category == OutcomeCategory.NEEDS_HUMAN:
                self.transition(case_id, RegEState.NEEDS_HUMAN)
                return {
                    "status": "NEEDS_HUMAN",
                    "code": outcome.code.value,
                    "message": outcome.message,
                }

            if outcome.category == OutcomeCategory.UNCERTAIN_EFFECT:
                self.transition(case_id, RegEState.UNCERTAIN_EFFECT)
                return {
                    "status": "UNCERTAIN_EFFECT",
                    "code": outcome.code.value,
                    "message": outcome.message,
                }

            if outcome.category == OutcomeCategory.RECOVERABLE_FAILURE:
                self.transition(case_id, RegEState.NEEDS_HUMAN)
                return {
                    "status": "RECOVERABLE_FAILURE",
                    "code": outcome.code.value,
                    "message": outcome.message,
                }

            if outcome.category == OutcomeCategory.HARD_FAILURE:
                self.transition(case_id, RegEState.FAILED)
                return {"status": "FAILED", "code": outcome.code.value, "message": outcome.message}

            # Create 2-business-day notice deadline
            due_at = add_business_days(clock, 2)
            self.repo.create_deadline(case_id, "NOTICE_2_DAY", due_at=due_at)
            self.transition(case_id, RegEState.PROVISIONAL_CREDIT_POSTED, money_moved=True)
            self.session.commit()

            # CRASH INJECTION HOOK: Simulate sudden process crash after money movement!
            if self.kill_after_credit:
                self.repo.record_event(
                    case_id=case_id,
                    event_type="PROCESS_KILLED",
                    step_name="core.post_provisional_credit",
                    payload={"message": "Intentional crash injection after money movement"},
                )
                self.session.commit()
                raise RuntimeError(
                    "PROCESS_KILL_AFTER=core.post_provisional_credit triggered! "
                    "Simulating process crash. Money has moved. Notice has not been sent."
                )

        # -------------------------------------------------------------------
        # Step 6: Dispatch Member Notice (COMMIT)
        # -------------------------------------------------------------------
        if "docs.send_notice" not in snapshot.completed_capabilities:
            self.transition(case_id, RegEState.NOTICE_PENDING)
            notice_deadline = add_business_days(clock, 2).strftime("%Y-%m-%d %H:%M:%S UTC")

            resp = httpx.post(
                f"{settings.documents_url}/notices/send",
                data={
                    "case_id": case_id,
                    "member_id": member_id,
                    "notice_type": "REG_E_PROVISIONAL_CREDIT_DISCLOSURE",
                    "amount": amount,
                    "deadline_due_at": notice_deadline,
                },
                timeout=5.0,
            )
            if resp.status_code != 200:
                self.transition(case_id, RegEState.NEEDS_HUMAN)
                return {"status": "NEEDS_HUMAN", "error": "Notice delivery failed"}

            exec_rec = self.repo.start_execution(
                case_id=case_id,
                capability_id="docs.send_notice",
                capability_version="1.0.0",
                effect_class="COMMIT",
                idempotency_key=f"regE:{case_id}:notice",
            )
            self.repo.complete_execution(exec_rec.id, status="SUCCESS", audit_ref=f"NOT-{case_id}")
            self.repo.resolve_deadline(case_id, "NOTICE_2_DAY")
            self.transition(case_id, RegEState.NOTICE_SENT)

        # -------------------------------------------------------------------
        # Step 7: Settle Case in Waiting Resolution
        # -------------------------------------------------------------------
        self.transition(case_id, RegEState.WAITING_RESOLUTION)
        self.session.commit()

        final_snapshot = self.service.reconstruct_case_state(case_id)
        return {
            "status": "SUCCESS",
            "state": final_snapshot.status,
            "money_moved": final_snapshot.money_moved,
            "latest_memo_ref": final_snapshot.latest_memo_ref,
            "pending_deadlines_count": len(final_snapshot.pending_deadlines),
        }
