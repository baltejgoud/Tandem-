"""Behavioral contracts for the audited safety and artifact boundaries."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from tandem.discovery.agent import DiscoveryAgent
from tandem.discovery.recorder import DiscoveryTrace
from tandem.domain.capability import CapabilityDefinition, load_capability_from_yaml
from tandem.domain.effects import EffectSpec
from tandem.domain.outcomes import OutcomeCategory, OutcomeCode
from tandem.policy.engine import PolicyEngine
from tandem.ledger.database import get_engine, get_session_factory, init_db
from tandem.replay.engine import EffectEngine
from tandem.replay.executor import DeterministicExecutor
from tandem.replay.postcheck import execute_postcheck
from tandem.replay.precheck import execute_precheck


ARTIFACT = Path("capabilities/compiled/demo_post_provisional_credit.yaml")


def _artifact_data() -> dict[str, object]:
    return yaml.safe_load(ARTIFACT.read_text(encoding="utf-8"))


def _write_tampered(tmp_path: Path, mutation) -> Path:
    data = _artifact_data()
    mutation(data)
    target = tmp_path / "tampered.yaml"
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def test_discovery_contract_requires_real_provider_and_durable_evidence() -> None:
    constructor = inspect.signature(DiscoveryAgent)
    assert "provider" in constructor.parameters
    assert "run_id" in DiscoveryTrace.model_fields
    assert "provider" in DiscoveryTrace.model_fields
    assert "model" in DiscoveryTrace.model_fields
    assert "events" in DiscoveryTrace.model_fields
    assert "evidence_directory" in DiscoveryTrace.model_fields


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["steps"][0].update(semantic_target="http://evil.invalid"),
        lambda data: data["effect"].update({"class": "READ"}),
        lambda data: data["effect"]["bounds"].update(max_amount="999999.99"),
    ],
    ids=["url", "effect-class", "policy-bound"],
)
def test_artifact_tampering_variants_are_rejected(tmp_path: Path, mutation) -> None:
    tampered = _write_tampered(tmp_path, mutation)
    with pytest.raises(ValueError, match="hash|integrity|tamper|digest"):
        load_capability_from_yaml(str(tampered))


def test_unsupported_artifact_schema_version_is_rejected(tmp_path: Path) -> None:
    assert "schema_version" in CapabilityDefinition.model_fields
    tampered = _write_tampered(tmp_path, lambda data: data.update(schema_version=999))
    with pytest.raises(ValueError, match="schema|version|unsupported"):
        load_capability_from_yaml(str(tampered))


def test_commit_contract_requires_structural_guard_and_reconciliation() -> None:
    assert "identity" in EffectSpec.model_fields
    assert "guard_ref" in CapabilityDefinition.model_fields["steps"].annotation.__args__[0].model_fields

    data = _artifact_data()
    data["effect"]["reconciliation"] = None
    data["steps"][-1]["guard_ref"] = None
    with pytest.raises(ValidationError):
        CapabilityDefinition.model_validate(data)


def test_postcheck_outage_is_explicit_and_never_success(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectTimeout("target unavailable")

    monkeypatch.setattr("tandem.replay.postcheck.httpx.get", unavailable)
    outcome = execute_postcheck(
        capability,
        {
            "institution_id": "alpha",
            "member_id": "8830142",
            "account_id": "CHK-8830142-01",
            "case_id": "D-POSTCHECK-DOWN",
            "amount": "340.00",
            "currency": "USD",
        },
    )
    assert outcome is not None
    assert outcome.category != OutcomeCategory.SUCCESS
    assert outcome.code in {OutcomeCode.POSTCHECK_UNCERTAIN, OutcomeCode.UNCERTAIN_EFFECT}


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_code"),
    [
        (500, {"error": "down"}, OutcomeCode.PRECHECK_UNAVAILABLE),
        (200, None, OutcomeCode.PRECHECK_INVALID_RESPONSE),
        (200, {"case_id": "D-PRECHECK", "status": "POSTED"}, OutcomeCode.PRECHECK_AMBIGUOUS),
        (
            200,
            {
                "case_id": "D-OTHER",
                "member_id": "8830142",
                "account_id": "CHK-8830142-01",
                "amount": "340.00",
                "memo_code": "MC-1",
                "status": "POSTED",
            },
            OutcomeCode.PRECHECK_AMBIGUOUS,
        ),
    ],
    ids=["http-500", "malformed-json", "missing-identity", "identity-mismatch"],
)
def test_precheck_non_absence_states_halt(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    payload: dict[str, object] | None,
    expected_code: OutcomeCode,
) -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))

    class Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self):
            if payload is None:
                raise ValueError("not json")
            return payload

    monkeypatch.setattr("tandem.replay.precheck.httpx.get", lambda *_args, **_kwargs: Response())
    outcome = execute_precheck(
        capability,
        {
            "institution_id": "alpha",
            "member_id": "8830142",
            "account_id": "CHK-8830142-01",
            "case_id": "D-PRECHECK",
            "amount": "340.00",
            "currency": "USD",
        },
    )
    assert outcome.code == expected_code
    assert outcome.category == OutcomeCategory.HARD_FAILURE


def test_precheck_outage_never_reaches_external_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))
    monkeypatch.setattr(
        "tandem.replay.precheck.httpx.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ConnectTimeout("down")),
    )
    engine = get_engine(str(tmp_path / "precheck-halt.db"))
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        effect_engine = EffectEngine(session, page=object())
        effect_engine.executor.execute = lambda *_args, **_kwargs: pytest.fail(
            "external mutation was reached while precheck was unavailable"
        )
        outcome = effect_engine.execute_capability(
            capability,
            {
                "institution_id": "alpha",
                "member_id": "8830142",
                "account_id": "CHK-8830142-01",
                "case_id": "D-PRECHECK-HALT",
                "amount": "340.00",
                "currency": "USD",
            },
        )
    assert outcome.code == OutcomeCode.PRECHECK_UNAVAILABLE


def test_guard_contract_requires_account_binding() -> None:
    guard_type = CapabilityDefinition.model_fields["scoped_guard"].annotation
    guard_model = next(arg for arg in guard_type.__args__ if arg is not type(None))
    assert "expected_account_template" in guard_model.model_fields


def test_guard_contract_requires_currency_binding() -> None:
    guard_type = CapabilityDefinition.model_fields["scoped_guard"].annotation
    guard_model = next(arg for arg in guard_type.__args__ if arg is not type(None))
    assert "expected_currency_template" in guard_model.model_fields


@pytest.mark.parametrize("bad_value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_money_is_rejected_at_input_boundary(bad_value: str) -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))
    outcome = PolicyEngine.evaluate(
        capability,
        {
            "institution_id": "alpha",
            "member_id": "8830142",
            "account_id": "CHK-8830142-01",
            "case_id": "D-NON-FINITE",
            "amount": bad_value,
            "currency": "USD",
        },
    )
    assert outcome is not None
    assert outcome.code in {OutcomeCode.POLICY_DENIED, OutcomeCode.POLICY_VIOLATION}


@pytest.mark.parametrize(
    ("amount", "allowed"),
    [
        ("0.00", False),
        ("0.01", True),
        ("340.00", True),
        ("499.99", True),
        ("500.00", True),
        ("500.01", False),
        ("999999999999999999.99", False),
    ],
)
def test_money_policy_boundary_table(amount: str, allowed: bool) -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))
    outcome = PolicyEngine.evaluate(
        capability,
        {
            "institution_id": "alpha",
            "member_id": "8830142",
            "account_id": "CHK-8830142-01",
            "case_id": f"D-BOUND-{amount}",
            "amount": Decimal(amount),
            "currency": "USD",
        },
    )
    assert (outcome is None) is allowed


def test_effect_identity_is_complete_and_deterministic() -> None:
    from tandem.domain.identity import EffectIdentity

    identity = EffectIdentity(
        institution_id="alpha",
        procedure_id="reg_e_dispute",
        case_id="D-IDENTITY",
        capability_id="core.post_provisional_credit",
        member_id="8830142",
        account_id="CHK-8830142-01",
        amount=Decimal("340.00"),
        currency="USD",
        business_reference="D-IDENTITY",
    )
    same = identity.model_copy()
    different_account = identity.model_copy(update={"account_id": "CHK-OTHER"})
    assert identity.idempotency_key == same.idempotency_key
    assert identity.idempotency_key != different_account.idempotency_key


def test_after_submit_unknown_is_not_generic_hard_failure() -> None:
    source = inspect.getsource(DeterministicExecutor.execute)
    assert "ExecutionPhase" in source
    assert "AFTER_SUBMIT_UNKNOWN" in source
    assert "POSSIBLY_APPLIED" in source or "UNCERTAIN_EFFECT" in source


def test_institution_routing_is_not_embedded_in_immutable_artifact() -> None:
    capability = load_capability_from_yaml(str(ARTIFACT))
    navigation_steps = [step for step in capability.steps if step.action.value == "NAVIGATE"]
    assert navigation_steps
    assert all("127.0.0.1" not in step.semantic_target for step in navigation_steps)
    assert "supported_surfaces" in CapabilityDefinition.model_fields
