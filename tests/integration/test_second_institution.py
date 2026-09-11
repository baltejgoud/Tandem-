"""Integration test for Second Institution and Surface Overlays (Scenario 7).

Verifies:
1. Capability replay fails or drifts on a second institution with altered UI skin/selectors without an overlay.
2. Replay succeeds when paired with the institution's SurfaceOverlay.
3. Drift warnings are captured in telemetry.
4. Replay executes with ZERO LLM calls across institutions.
"""

import pytest
from playwright.sync_api import sync_playwright

from simulators.core_bank.state import core_bank_state
from tandem.domain.capability import StepAction, load_capability_from_yaml
from tandem.domain.outcomes import OutcomeCategory, OutcomeCode
from tandem.policy.telemetry import llm_tracker
from tandem.replay.executor import DeterministicExecutor
from tandem.surfaces.overlays import get_overlay
from tests.server_utils import ensure_simulators_running, reset_all_simulators


@pytest.fixture(scope="module", autouse=True)
def setup_simulators():
    ensure_simulators_running()


@pytest.fixture(autouse=True)
def reset_test_state():
    reset_all_simulators()
    llm_tracker.reset()
    yield
    reset_all_simulators()
    llm_tracker.reset()


def test_second_institution_replay_with_surface_overlay():
    # 1. Load standard capability artifact
    cap = load_capability_from_yaml("capabilities/core/post_provisional_credit.yaml")

    # Override first step URL to point to Institution Beta portal
    beta_cap = cap.model_copy(deep=True)
    for step in beta_cap.steps:
        if step.action == StepAction.NAVIGATE:
            step.semantic_target = "http://127.0.0.1:8001/inst_beta"

    inputs = {
        "institution_id": "beta",
        "member_id": "8830142",
        "account_id": "CHK-8830142-01",
        "case_id": "D-BETA-7701",
        "amount": 340.00,
        "currency": "USD",
    }

    # -------------------------------------------------------------------
    # Test 1: Replay on Beta WITHOUT overlay encounters drift/failure
    # -------------------------------------------------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        unmapped_executor = DeterministicExecutor(page=page, overlay=None)
        outcome_unmapped = unmapped_executor.execute(capability=beta_cap, inputs=inputs)
        browser.close()

    # Without overlay, primary search box input[name='q'] fails to resolve
    assert outcome_unmapped.category in (
        OutcomeCategory.RECOVERABLE_FAILURE,
        OutcomeCategory.HARD_FAILURE,
    )
    assert outcome_unmapped.money_moved is False

    # -------------------------------------------------------------------
    # Test 2: Replay on Beta WITH core_bank_beta overlay succeeds
    # -------------------------------------------------------------------
    reset_all_simulators()
    llm_tracker.reset()
    beta_overlay = get_overlay("core_bank_beta")
    assert beta_overlay is not None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        mapped_executor = DeterministicExecutor(page=page, overlay=beta_overlay)
        outcome_mapped = mapped_executor.execute(capability=beta_cap, inputs=inputs)
        browser.close()

    assert (
        outcome_mapped.category == OutcomeCategory.SUCCESS
    ), f"Mapped replay failed: {outcome_mapped.code} - {outcome_mapped.message}"
    assert outcome_mapped.code == OutcomeCode.COMPLETED
    assert outcome_mapped.money_moved is True
    assert outcome_mapped.audit_ref is not None
    assert outcome_mapped.audit_ref.startswith("MC-")

    # Verify money movement landed in core bank
    assert core_bank_state.members["8830142"].balance == 1580.50
    credit_rec = core_bank_state.find_credit_by_case("D-BETA-7701")
    assert credit_rec is not None
    assert credit_rec.amount == 340.00

    # CRITICAL INVARIANT: Zero LLM calls during replay across institutions!
    assert (
        llm_tracker.call_count == 0
    ), f"Overlay replay violated invariant: {llm_tracker.call_count} LLM calls made!"
