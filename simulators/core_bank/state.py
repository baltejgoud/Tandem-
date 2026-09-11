"""In-memory state and data structures for the Hostile Core Banking Simulator."""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from tandem.domain.money import parse_money


@dataclass
class Transaction:
    txn_id: str
    posted_at: str
    description: str
    amount: Decimal
    card_last4: str
    status: str = "SETTLED"


@dataclass
class ProvisionalCredit:
    credit_id: str
    case_id: str
    member_id: str
    account_id: str
    amount: Decimal
    memo_code: str
    posted_at: str
    status: str = "POSTED"


@dataclass
class Member:
    member_id: str
    first_name: str
    last_name: str
    account_id: str
    balance: Decimal
    transactions: List[Transaction] = field(default_factory=list)


class CoreBankState:
    """Thread-safe in-memory store for the core banking platform."""

    def __init__(self):
        self.members: Dict[str, Member] = {}
        self.credits: Dict[str, ProvisionalCredit] = {}  # key: case_id
        self.session_valid: bool = True
        self.require_compliance_interstitial: bool = False
        self.compliance_cleared: bool = False
        self.simulate_latency_ms: int = 0
        self.simulate_post_commit_delay_ms: int = 0
        self.fail_credit_lookup_when_present: bool = False
        self.seed()

    def seed(self):
        """Seed deterministic test data as specified."""
        self.members.clear()
        self.credits.clear()
        self.session_valid = True
        self.require_compliance_interstitial = False
        self.compliance_cleared = False
        self.simulate_latency_ms = 0
        self.simulate_post_commit_delay_ms = 0
        self.fail_credit_lookup_when_present = False

        # Primary test member
        self.members["8830142"] = Member(
            member_id="8830142",
            first_name="Jane",
            last_name="DisputeMember",
            account_id="CHK-8830142-01",
            balance=Decimal("1240.50"),
            transactions=[
                Transaction(
                    txn_id="TXN-99101",
                    posted_at="2026-09-01 14:22:10",
                    description="POS DEBIT - ELECTRONICS STORE",
                    amount=Decimal("340.00"),
                    card_last4="4112",
                ),
                Transaction(
                    txn_id="TXN-99088",
                    posted_at="2026-08-28 09:15:00",
                    description="GROCERY MARKET",
                    amount=Decimal("85.20"),
                    card_last4="4112",
                ),
            ],
        )

        # Confusable test member (transposed digits)
        self.members["8830124"] = Member(
            member_id="8830124",
            first_name="John",
            last_name="ConfusableMember",
            account_id="CHK-8830124-01",
            balance=Decimal("410.25"),
            transactions=[
                Transaction(
                    txn_id="TXN-99042",
                    posted_at="2026-08-25 11:05:12",
                    description="COFFEE SHOP",
                    amount=Decimal("4.50"),
                    card_last4="8890",
                )
            ],
        )

    def search_members(self, query: str, randomize_order: bool = True) -> List[Member]:
        """Fuzzy search returning matching members in intentionally non-deterministic order."""
        query = query.strip().lower()
        results = [
            m
            for m in self.members.values()
            if query in m.member_id.lower()
            or query in m.last_name.lower()
            or query in m.account_id.lower()
        ]
        if randomize_order and len(results) > 1:
            # Deliberate hostility: non-deterministic row order
            random.shuffle(results)
        return results

    def post_credit(self, case_id: str, member_id: str, amount: Decimal) -> ProvisionalCredit:
        """Apply provisional credit to member account."""
        if member_id not in self.members:
            raise ValueError(f"Member {member_id} not found")

        member = self.members[member_id]
        amount = parse_money(amount)
        memo_code = f"MC-{random.randint(7000, 7999)}"
        credit = ProvisionalCredit(
            credit_id=f"CRD-{random.randint(10000, 99999)}",
            case_id=case_id,
            member_id=member_id,
            account_id=member.account_id,
            amount=amount,
            memo_code=memo_code,
            posted_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )
        self.credits[case_id] = credit
        member.balance += amount
        return credit

    def find_credit_by_case(self, case_id: str) -> Optional[ProvisionalCredit]:
        return self.credits.get(case_id)


# Global singleton state for core bank
core_bank_state = CoreBankState()
