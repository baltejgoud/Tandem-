"""Data access repository for procedure ledger operations."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from tandem.ledger.models import (
    CapabilityExecutionRecord,
    DeadlineRecord,
    EffectIntentRecord,
    HumanHandoffRecord,
    LeaseRecord,
    ProcedureCaseRecord,
    ProcedureEventRecord,
)


class LedgerRepository:
    """Encapsulates all database operations for the append-only procedure ledger."""

    def __init__(self, session: Session):
        self.session = session

    # -----------------------------------------------------------------------
    # Case Operations
    # -----------------------------------------------------------------------
    def get_case(self, case_id: str) -> Optional[ProcedureCaseRecord]:
        stmt = select(ProcedureCaseRecord).where(ProcedureCaseRecord.case_id == case_id)
        return self.session.scalar(stmt)

    def create_or_get_case(
        self,
        case_id: str,
        member_id: str,
        amount: float = 0.0,
        currency: str = "USD",
        procedure_name: str = "reg_e_dispute",
    ) -> ProcedureCaseRecord:
        case = self.get_case(case_id)
        if not case:
            case = ProcedureCaseRecord(
                case_id=case_id,
                member_id=member_id,
                amount=amount,
                currency=currency,
                procedure_name=procedure_name,
                status="RECEIVED",
            )
            self.session.add(case)
            self.session.flush()
        return case

    def update_case_status(
        self, case_id: str, status: str, money_moved: Optional[bool] = None
    ) -> ProcedureCaseRecord:
        case = self.get_case(case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")
        case.status = status
        if money_moved is not None:
            case.money_moved = case.money_moved or money_moved
        case.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return case

    # -----------------------------------------------------------------------
    # Event Log
    # -----------------------------------------------------------------------
    def record_event(
        self,
        case_id: str,
        event_type: str,
        step_name: str,
        actor: str = "AUTOMATION",
        payload: Optional[Dict[str, Any]] = None,
    ) -> ProcedureEventRecord:
        event = ProcedureEventRecord(
            case_id=case_id,
            event_type=event_type,
            step_name=step_name,
            actor=actor,
            payload=json.dumps(payload) if payload else None,
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get_events_for_case(self, case_id: str) -> List[ProcedureEventRecord]:
        stmt = (
            select(ProcedureEventRecord)
            .where(ProcedureEventRecord.case_id == case_id)
            .order_by(ProcedureEventRecord.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    # -----------------------------------------------------------------------
    # Capability Execution Tracking
    # -----------------------------------------------------------------------
    def start_execution(
        self,
        case_id: str,
        capability_id: str,
        capability_version: str,
        effect_class: str,
        idempotency_key: Optional[str] = None,
        expected_entity: Optional[str] = None,
        expected_amount: Optional[float] = None,
        actor: str = "AUTOMATION",
        browser_session_id: Optional[str] = None,
    ) -> CapabilityExecutionRecord:
        record = CapabilityExecutionRecord(
            case_id=case_id,
            capability_id=capability_id,
            capability_version=capability_version,
            effect_class=effect_class,
            idempotency_key=idempotency_key,
            status="RUNNING",
            expected_entity=expected_entity,
            expected_amount=expected_amount,
            actor=actor,
            browser_session_id=browser_session_id,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def complete_execution(
        self,
        execution_id: int,
        status: str,
        observed_entity: Optional[str] = None,
        observed_amount: Optional[float] = None,
        failure_category: Optional[str] = None,
        audit_ref: Optional[str] = None,
        money_moved: bool = False,
    ) -> CapabilityExecutionRecord:
        stmt = select(CapabilityExecutionRecord).where(CapabilityExecutionRecord.id == execution_id)
        record = self.session.scalar(stmt)
        if not record:
            raise ValueError(f"Execution record {execution_id} not found")

        record.status = status
        record.observed_entity = observed_entity
        record.observed_amount = observed_amount
        record.failure_category = failure_category
        record.audit_ref = audit_ref
        record.money_moved = money_moved
        record.completed_at = datetime.now(timezone.utc)
        self.session.flush()
        return record

    def get_executions_for_case(self, case_id: str) -> List[CapabilityExecutionRecord]:
        stmt = (
            select(CapabilityExecutionRecord)
            .where(CapabilityExecutionRecord.case_id == case_id)
            .order_by(CapabilityExecutionRecord.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    # -----------------------------------------------------------------------
    # Effect Intent
    # -----------------------------------------------------------------------
    def stage_intent(
        self, case_id: str, idempotency_key: str, capability_id: str
    ) -> EffectIntentRecord:
        intent = EffectIntentRecord(
            case_id=case_id,
            idempotency_key=idempotency_key,
            capability_id=capability_id,
            intent_status="STAGED",
        )
        self.session.add(intent)
        self.session.flush()
        return intent

    def find_intent(self, idempotency_key: str) -> Optional[EffectIntentRecord]:
        stmt = select(EffectIntentRecord).where(
            EffectIntentRecord.idempotency_key == idempotency_key
        )
        return self.session.scalar(stmt)

    def mark_intent_committed(self, idempotency_key: str) -> None:
        intent = self.find_intent(idempotency_key)
        if intent:
            intent.intent_status = "COMMITTED"
            self.session.flush()

    # -----------------------------------------------------------------------
    # Deadlines
    # -----------------------------------------------------------------------
    def create_deadline(self, case_id: str, deadline_type: str, due_at: datetime) -> DeadlineRecord:
        record = DeadlineRecord(
            case_id=case_id,
            deadline_type=deadline_type,
            due_at=due_at,
            status="PENDING",
        )
        self.session.add(record)
        self.session.flush()
        return record

    def resolve_deadline(self, case_id: str, deadline_type: str) -> Optional[DeadlineRecord]:
        stmt = select(DeadlineRecord).where(
            DeadlineRecord.case_id == case_id,
            DeadlineRecord.deadline_type == deadline_type,
            DeadlineRecord.status == "PENDING",
        )
        record = self.session.scalar(stmt)
        if record:
            record.status = "MET"
            record.resolved_at = datetime.now(timezone.utc)
            self.session.flush()
        return record

    def get_deadlines_for_case(self, case_id: str) -> List[DeadlineRecord]:
        stmt = select(DeadlineRecord).where(DeadlineRecord.case_id == case_id)
        return list(self.session.scalars(stmt).all())

    # -----------------------------------------------------------------------
    # Single-Owner Lease (AUTOMATION vs HUMAN)
    # -----------------------------------------------------------------------
    def acquire_lease(self, case_id: str, owner: str) -> LeaseRecord:
        stmt = select(LeaseRecord).where(LeaseRecord.case_id == case_id)
        lease = self.session.scalar(stmt)
        if not lease:
            lease = LeaseRecord(case_id=case_id, owner=owner)
            self.session.add(lease)
        else:
            lease.owner = owner
            lease.acquired_at = datetime.now(timezone.utc)
            lease.released_at = None
        self.session.flush()
        return lease

    def get_lease(self, case_id: str) -> Optional[LeaseRecord]:
        stmt = select(LeaseRecord).where(LeaseRecord.case_id == case_id)
        return self.session.scalar(stmt)

    def release_lease(self, case_id: str) -> Optional[LeaseRecord]:
        lease = self.get_lease(case_id)
        if lease:
            lease.released_at = datetime.now(timezone.utc)
            self.session.flush()
        return lease

    # -----------------------------------------------------------------------
    # Human Handoff
    # -----------------------------------------------------------------------
    def record_handoff(
        self, case_id: str, reason: str, operator_id: str, action_taken: str
    ) -> HumanHandoffRecord:
        handoff = HumanHandoffRecord(
            case_id=case_id,
            reason=reason,
            operator_id=operator_id,
            action_taken=action_taken,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        self.session.add(handoff)
        self.session.flush()
        return handoff
