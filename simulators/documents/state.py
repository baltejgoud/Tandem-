"""Independent durable state for the member-notice simulator."""

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
class MemberNotice:
    notice_id: str
    case_id: str
    member_id: str
    notice_type: str
    amount: Decimal
    deadline_due_at: str
    sent_at: str
    status: str = "SENT"


class DocumentSystemState:
    """SQLite-backed notice effects with case-key idempotency."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(
            Path(db_path or os.environ.get("TANDEM_DOCUMENTS_SIM_DB", "documents_simulator.db")).resolve()
        )
        self.simulate_failure = False
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
                CREATE TABLE IF NOT EXISTS notices (
                    case_id TEXT PRIMARY KEY,
                    notice_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    notice_type TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    deadline_due_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_history (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    notice_reference TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )

    @property
    def notices(self) -> Dict[str, MemberNotice]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM notices").fetchall()
        return {row["case_id"]: self._from_row(row) for row in rows}

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM effect_history")
            connection.execute("DELETE FROM notices")
        self.simulate_failure = False

    def send_notice(
        self,
        case_id: str,
        member_id: str,
        notice_type: str,
        amount: Decimal,
        deadline_due_at: str,
    ) -> MemberNotice:
        amount = parse_money(amount)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM notices WHERE case_id = ?", (case_id,)
            ).fetchone()
            if existing:
                notice = self._from_row(existing)
                if (
                    notice.member_id != member_id
                    or notice.notice_type != notice_type
                    or notice.amount != amount
                    or notice.deadline_due_at != deadline_due_at
                ):
                    raise ValueError(f"Case {case_id} already has a different notice identity")
                return notice
            notice = MemberNotice(
                notice_id=f"NOT-{random.randint(1000, 9999)}",
                case_id=case_id,
                member_id=member_id,
                notice_type=notice_type,
                amount=amount,
                deadline_due_at=deadline_due_at,
                sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )
            connection.execute(
                "INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    notice.case_id,
                    notice.notice_id,
                    notice.member_id,
                    notice.notice_type,
                    str(notice.amount),
                    notice.deadline_due_at,
                    notice.sent_at,
                    notice.status,
                ),
            )
            connection.execute(
                """INSERT INTO effect_history
                   (case_id, effect_type, notice_reference, recorded_at)
                   VALUES (?, 'NOTICE_SENT', ?, ?)""",
                (case_id, notice.notice_id, notice.sent_at),
            )
            return notice

    def find_by_case(self, case_id: str) -> Optional[MemberNotice]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notices WHERE case_id = ?", (case_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def effect_count(self, case_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM effect_history WHERE case_id = ?", (case_id,)
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemberNotice:
        return MemberNotice(
            notice_id=row["notice_id"],
            case_id=row["case_id"],
            member_id=row["member_id"],
            notice_type=row["notice_type"],
            amount=parse_money(row["amount"]),
            deadline_due_at=row["deadline_due_at"],
            sent_at=row["sent_at"],
            status=row["status"],
        )

    def close(self) -> None:
        """Connections are operation-scoped; retained for lifecycle symmetry."""


document_state = DocumentSystemState()
