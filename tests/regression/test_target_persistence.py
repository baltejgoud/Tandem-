"""Durability and idempotency contracts for external-system simulators."""

from decimal import Decimal
from pathlib import Path

from simulators.core_bank.state import CoreBankState
from simulators.documents.state import DocumentSystemState
from simulators.processor.state import ProcessorState


def test_core_effect_survives_restart_and_keeps_history(tmp_path: Path) -> None:
    db_path = str(tmp_path / "core.db")
    first = CoreBankState(db_path=db_path, institution_id="alpha")
    first.seed()
    credit = first.post_credit(
        "D-DURABLE-CORE",
        "8830142",
        Decimal("340.00"),
        currency="USD",
        business_reference="D-DURABLE-CORE",
    )
    first.close()

    restarted = CoreBankState(db_path=db_path, institution_id="alpha")
    found = restarted.find_credit_by_case("D-DURABLE-CORE")
    assert found == credit
    assert restarted.effect_count("D-DURABLE-CORE") == 1
    assert restarted.get_member("8830142").balance == Decimal("1580.50")


def test_processor_effect_is_durable_and_idempotent(tmp_path: Path) -> None:
    db_path = str(tmp_path / "processor.db")
    first = ProcessorState(db_path=db_path)
    one = first.file_chargeback("D-DURABLE-CB", "4112", Decimal("340.00"))
    two = first.file_chargeback("D-DURABLE-CB", "4112", Decimal("340.00"))
    assert one == two
    assert first.effect_count("D-DURABLE-CB") == 1
    first.close()

    restarted = ProcessorState(db_path=db_path)
    assert restarted.find_by_case("D-DURABLE-CB") == one
    assert restarted.effect_count("D-DURABLE-CB") == 1


def test_notice_effect_is_durable_and_idempotent(tmp_path: Path) -> None:
    db_path = str(tmp_path / "documents.db")
    first = DocumentSystemState(db_path=db_path)
    one = first.send_notice(
        "D-DURABLE-NOTICE",
        "8830142",
        "REG_E_PROVISIONAL_CREDIT_DISCLOSURE",
        Decimal("340.00"),
        "2026-09-15T17:00:00-04:00",
    )
    two = first.send_notice(
        "D-DURABLE-NOTICE",
        "8830142",
        "REG_E_PROVISIONAL_CREDIT_DISCLOSURE",
        Decimal("340.00"),
        "2026-09-15T17:00:00-04:00",
    )
    assert one == two
    assert first.effect_count("D-DURABLE-NOTICE") == 1
    first.close()

    restarted = DocumentSystemState(db_path=db_path)
    assert restarted.find_by_case("D-DURABLE-NOTICE") == one
    assert restarted.effect_count("D-DURABLE-NOTICE") == 1

