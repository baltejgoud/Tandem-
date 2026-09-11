"""State and models for member notice / document delivery system."""

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class MemberNotice:
    notice_id: str
    case_id: str
    member_id: str
    notice_type: str
    amount: float
    deadline_due_at: str
    sent_at: str
    status: str = "SENT"


class DocumentSystemState:
    """In-memory store for member notices."""

    def __init__(self):
        self.notices: Dict[str, MemberNotice] = {}  # key: case_id
        self.simulate_failure: bool = False

    def reset(self):
        self.notices.clear()
        self.simulate_failure = False

    def send_notice(
        self,
        case_id: str,
        member_id: str,
        notice_type: str,
        amount: float,
        deadline_due_at: str,
    ) -> MemberNotice:
        notice = MemberNotice(
            notice_id=f"NOT-{random.randint(1000, 9999)}",
            case_id=case_id,
            member_id=member_id,
            notice_type=notice_type,
            amount=amount,
            deadline_due_at=deadline_due_at,
            sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            status="SENT",
        )
        self.notices[case_id] = notice
        return notice

    def find_by_case(self, case_id: str) -> Optional[MemberNotice]:
        return self.notices.get(case_id)


document_state = DocumentSystemState()
