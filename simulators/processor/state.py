"""Independent durable state for the card-processor simulator."""

from __future__ import annotations

import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from tandem.domain.money import parse_money


@dataclass(frozen=True)
class Chargeback:
    chargeback_id: str
    case_id: str
    card_last4: str
    amount: Decimal
    dispute_reason: str
    network_ref: str
    created_at: str
    status: str = "FILED"


class ProcessorState:
    """SQLite-backed processor effects with case-key idempotency."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(
            Path(db_path or os.environ.get("TANDEM_PROCESSOR_SIM_DB", "processor_simulator.db")).resolve()
        )
        self.session_expired = False
        self.timeout_after_submit = False
        self.system_failure = False
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chargebacks (
                    case_id TEXT PRIMARY KEY,
                    chargeback_id TEXT NOT NULL,
                    card_last4 TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    dispute_reason TEXT NOT NULL,
                    network_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_history (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    processor_reference TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )

    @property
    def chargebacks(self) -> Dict[str, Chargeback]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM chargebacks").fetchall()
        return {row["case_id"]: self._from_row(row) for row in rows}

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM effect_history")
            connection.execute("DELETE FROM chargebacks")
        self.session_expired = False
        self.timeout_after_submit = False
        self.system_failure = False

    def file_chargeback(
        self,
        case_id: str,
        card_last4: str,
        amount: Decimal,
        dispute_reason: str = "Unauthorized Debit",
    ) -> Chargeback:
        amount = parse_money(amount)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM chargebacks WHERE case_id = ?", (case_id,)
            ).fetchone()
            if existing:
                chargeback = self._from_row(existing)
                if (
                    chargeback.card_last4 != card_last4
                    or chargeback.amount != amount
                    or chargeback.dispute_reason != dispute_reason
                ):
                    raise ValueError(f"Case {case_id} already has a different chargeback identity")
                return chargeback
            chargeback = Chargeback(
                chargeback_id=f"CB-{random.randint(50000, 59999)}",
                case_id=case_id,
                card_last4=card_last4,
                amount=amount,
                dispute_reason=dispute_reason,
                network_ref=f"VISA-DISP-{random.randint(10000, 99999)}",
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )
            connection.execute(
                "INSERT INTO chargebacks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chargeback.case_id,
                    chargeback.chargeback_id,
                    chargeback.card_last4,
                    str(chargeback.amount),
                    chargeback.dispute_reason,
                    chargeback.network_ref,
                    chargeback.created_at,
                    chargeback.status,
                ),
            )
            connection.execute(
                """INSERT INTO effect_history
                   (case_id, effect_type, processor_reference, recorded_at)
                   VALUES (?, 'CHARGEBACK_FILED', ?, ?)""",
                (case_id, chargeback.network_ref, chargeback.created_at),
            )
            return chargeback

    def find_by_case(self, case_id: str) -> Optional[Chargeback]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chargebacks WHERE case_id = ?", (case_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def effect_count(self, case_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM effect_history WHERE case_id = ?", (case_id,)
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Chargeback:
        return Chargeback(
            chargeback_id=row["chargeback_id"],
            case_id=row["case_id"],
            card_last4=row["card_last4"],
            amount=parse_money(row["amount"]),
            dispute_reason=row["dispute_reason"],
            network_ref=row["network_ref"],
            created_at=row["created_at"],
            status=row["status"],
        )

    def close(self) -> None:
        """Connections are operation-scoped; retained for lifecycle symmetry."""


processor_state = ProcessorState()
