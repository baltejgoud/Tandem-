"""State and data models for the Card Processor Portal simulator."""

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class Chargeback:
    chargeback_id: str
    case_id: str
    card_last4: str
    amount: float
    dispute_reason: str
    network_ref: str
    created_at: str
    status: str = "FILED"


class ProcessorState:
    """Thread-safe state for card processor portal (CO-OP / PSCU / Visa DPS)."""

    def __init__(self):
        self.chargebacks: Dict[str, Chargeback] = {}  # key: case_id
        self.session_expired: bool = False
        self.timeout_after_submit: bool = False
        self.system_failure: bool = False

    def reset(self):
        self.chargebacks.clear()
        self.session_expired = False
        self.timeout_after_submit = False
        self.system_failure = False

    def file_chargeback(
        self,
        case_id: str,
        card_last4: str,
        amount: float,
        dispute_reason: str = "Unauthorized Debit",
    ) -> Chargeback:
        network_ref = f"VISA-DISP-{random.randint(10000, 99999)}"
        cb = Chargeback(
            chargeback_id=f"CB-{random.randint(50000, 59999)}",
            case_id=case_id,
            card_last4=card_last4,
            amount=amount,
            dispute_reason=dispute_reason,
            network_ref=network_ref,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )
        self.chargebacks[case_id] = cb
        return cb

    def find_by_case(self, case_id: str) -> Optional[Chargeback]:
        return self.chargebacks.get(case_id)


processor_state = ProcessorState()
