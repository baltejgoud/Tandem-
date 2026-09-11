"""Hard process-death matrix around the provisional-credit COMMIT."""

from __future__ import annotations

import multiprocessing
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from simulators.core_bank.state import core_bank_state
from simulators.documents.state import document_state
from tandem.ledger.database import get_engine, get_session_factory, init_db
from tandem.ledger.repository import LedgerRepository
from tandem.workflow.reg_e import RegEWorkflow

CRASH_POINTS = [
    "A_BEFORE_OBLIGATION",
    "B_AFTER_OBLIGATION",
    "C_AFTER_CLAIM",
    "D_AFTER_PRECHECK",
    "E_AFTER_GUARD",
    "F_BEFORE_SUBMIT",
    "G_AFTER_TARGET_ACCEPTS",
    "H_BEFORE_POSTCHECK",
    "I_AFTER_POSTCHECK",
    "J_BEFORE_FINAL_LEDGER_EVENT",
    "K_BEFORE_NOTICE",
    "L_AFTER_NOTICE",
]


def _crashing_workflow(db_path: str, case_id: str, point: str) -> None:
    os.environ["TANDEM_CRASH_POINT"] = point
    engine = get_engine(db_path)
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        RegEWorkflow(session, browser.new_page()).run_case(
            case_id,
            "8830142",
            "340.00",
            injected_clock=datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc),
        )
        browser.close()


def _recover_workflow(db_path: str, case_id: str, queue) -> None:
    os.environ.pop("TANDEM_CRASH_POINT", None)
    engine = get_engine(db_path)
    init_db(engine)
    factory = get_session_factory(engine)
    try:
        with factory() as session, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            result = RegEWorkflow(session, browser.new_page()).run_case(
                case_id,
                "8830142",
                "340.00",
                injected_clock=datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc),
            )
            browser.close()
            queue.put(result)
    except Exception as exc:
        queue.put({"status": "EXCEPTION", "error": repr(exc)})
    finally:
        engine.dispose()


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_hard_process_death_preserves_safety_and_recovers(
    crash_point: str, tmp_path: Path
) -> None:
    context = multiprocessing.get_context("spawn")
    case_id = f"D-CRASH-{crash_point[0]}"
    db_path = str(tmp_path / f"{crash_point}.db")
    process = context.Process(target=_crashing_workflow, args=(db_path, case_id, crash_point))
    process.start()
    process.join(timeout=60)
    assert process.exitcode == 86

    engine = get_engine(db_path)
    factory = get_session_factory(engine)
    with factory() as session:
        repo = LedgerRepository(session)
        obligations = repo.get_obligations_for_case(case_id)
    engine.dispose()

    target_credit = core_bank_state.find_credit_by_case(case_id)
    target_notice = document_state.find_by_case(case_id)
    if crash_point == "A_BEFORE_OBLIGATION":
        assert obligations == []
    else:
        assert len(obligations) == 1
    if crash_point[0] in {"G", "H", "I", "J", "K", "L"}:
        assert target_credit is not None
        assert obligations, "money moved without a durable notice obligation"
    else:
        assert target_credit is None
    assert (target_notice is not None) is (crash_point == "L_AFTER_NOTICE")

    queue = context.Queue()
    recovery = context.Process(target=_recover_workflow, args=(db_path, case_id, queue))
    recovery.start()
    recovery.join(timeout=60)
    assert recovery.exitcode == 0
    result = queue.get(timeout=5)
    assert result["status"] == "SUCCESS", result
    assert core_bank_state.effect_count(case_id) == 1
    assert document_state.effect_count(case_id) == 1

    reopened = get_engine(db_path)
    reopened_factory = get_session_factory(reopened)
    with reopened_factory() as session:
        final_obligations = LedgerRepository(session).get_obligations_for_case(case_id)
    reopened.dispose()
    assert len(final_obligations) == 1
    assert final_obligations[0].status == "SATISFIED"
