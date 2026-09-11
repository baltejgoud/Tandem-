"""End-to-end test verifying discovery, capability compilation, and zero-LLM replay.

Invariants verified:
1. Discovery agent records exploratory trace and tracks LLM calls (llm_call_count > 0).
2. Compiler transforms trace into validated, versioned YAML artifact with SHA-256 integrity hash.
3. Replay of the compiled artifact posts credit successfully.
4. Replay executes with ZERO LLM calls (llm_call_count == 0).
"""

from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

from simulators.core_bank.state import core_bank_state
from tandem.discovery.agent import DiscoveryAgent
from tandem.discovery.compiler import CapabilityCompiler
from tandem.domain.capability import load_capability_from_yaml
from tandem.domain.outcomes import OutcomeCategory, OutcomeCode
from tandem.policy.telemetry import llm_tracker
from tandem.replay.executor import DeterministicExecutor
from tests.server_utils import ensure_simulators_running, reset_all_simulators


@pytest.fixture(scope="module", autouse=True)
def setup_simulators():
    ensure_simulators_running()


@pytest.fixture(autouse=True)
def reset_test_state():
    reset_all_simulators()
    llm_tracker.reset()


def test_discovery_compilation_and_zero_llm_replay(tmp_path: Path):
    # =======================================================================
    # PHASE 1: Discovery (Model-Driven Exploration)
    # =======================================================================
    llm_tracker.reset()
    assert llm_tracker.call_count == 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        agent = DiscoveryAgent(page=page)
        discovery_inputs = {
            "member_id": "8830142",
            "case_id": "D-DISC-001",
            "amount": 340.00,
        }
        trace = agent.discover_provisional_credit(inputs=discovery_inputs)
        browser.close()

    # Verify discovery outcomes and telemetry
    assert trace.money_moved is True
    assert trace.discovered_memo is not None
    assert trace.discovered_memo.startswith("MC-")
    assert len(trace.actions) >= 5

    # INVARIANT: Discovery Phase DOES invoke LLM calls
    discovery_llm_calls = llm_tracker.call_count
    assert discovery_llm_calls > 0, f"Expected LLM calls during discovery, got {discovery_llm_calls}"

    # =======================================================================
    # PHASE 2: Compilation (Synthesize Typed, Versioned Capability Artifact)
    # =======================================================================
    compiler = CapabilityCompiler(output_dir=str(tmp_path / "compiled"))
    compiled_cap, artifact_path = compiler.compile(
        trace=trace,
        target_filename="core_post_provisional_credit.yaml",
    )

    assert artifact_path.exists()
    assert compiled_cap.artifact_hash is not None
    assert len(compiled_cap.artifact_hash) == 64

    # Verify compiled artifact is self-contained and valid
    loaded_cap = load_capability_from_yaml(str(artifact_path))
    assert loaded_cap.id == "core.post_provisional_credit"
    assert loaded_cap.effect.effect_class.value == "COMMIT"
    assert loaded_cap.scoped_guard is not None
    assert loaded_cap.scoped_guard.container_selector == "#credit_action_container, .confirm-panel"

    # =======================================================================
    # PHASE 3: Replay Compiled Artifact on New Case (Zero-LLM Invariant)
    # =======================================================================
    # Reset external state and LLM counter
    reset_all_simulators()
    llm_tracker.reset()
    assert llm_tracker.call_count == 0

    # Execute deterministic replay of the compiled artifact
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        executor = DeterministicExecutor(page=page)
        replay_inputs = {
            "member_id": "8830142",
            "case_id": "D-REPLAY-9901",
            "amount": 340.00,
        }
        outcome = executor.execute(capability=loaded_cap, inputs=replay_inputs)
        browser.close()

    # Verify successful execution of the compiled artifact
    assert outcome.category == OutcomeCategory.SUCCESS, f"Replay failed: {outcome.code} - {outcome.message}"
    assert outcome.code == OutcomeCode.COMPLETED
    assert outcome.money_moved is True
    assert outcome.audit_ref is not None
    assert outcome.audit_ref.startswith("MC-")

    # Verify money movement in target core banking simulator
    assert core_bank_state.members["8830142"].balance == 1580.50
    credit_record = core_bank_state.find_credit_by_case("D-REPLAY-9901")
    assert credit_record is not None
    assert credit_record.amount == 340.00
    assert credit_record.memo_code == outcome.audit_ref

    # CRITICAL ARCHITECTURAL INVARIANT: Replay must execute with ZERO LLM calls!
    assert (
        llm_tracker.call_count == 0
    ), f"Replay of compiled artifact violated invariant: made {llm_tracker.call_count} LLM calls!"
