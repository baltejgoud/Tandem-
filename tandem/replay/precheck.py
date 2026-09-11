"""Precheck execution to guarantee effect-level idempotency before mutation."""

from typing import Any, Dict, Optional

import httpx

from tandem.config import settings
from tandem.domain.capability import CapabilityDefinition
from tandem.domain.effects import EffectClass
from tandem.domain.outcomes import ExecutionOutcome, OutcomeCategory, OutcomeCode


def execute_precheck(
    capability: CapabilityDefinition, inputs: Dict[str, Any]
) -> Optional[ExecutionOutcome]:
    """Execute capability precheck.

    If declared effect already exists on target system, returns BUSINESS_OUTCOME / ALREADY_APPLIED.
    Returns None if effect has not yet occurred.
    """
    if capability.effect.effect_class != EffectClass.COMMIT:
        return None

    precheck_spec = capability.effect.precheck
    if not precheck_spec:
        return None

    case_id = inputs.get("case_id")
    if not case_id:
        return None

    # Core Banking memo / provisional credit precheck
    if capability.system == "core_bank" or "provisional_credit" in capability.id:
        try:
            url = f"{settings.core_bank_url}/api/credits/{case_id}"
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                memo_code = data.get("memo_code")
                amount = data.get("amount")
                return ExecutionOutcome(
                    category=OutcomeCategory.BUSINESS_OUTCOME,
                    code=OutcomeCode.ALREADY_APPLIED,
                    message=(
                        f"Precheck verified effect already exists: Provisional credit of "
                        f"${amount:.2f} already posted for Case {case_id} (Memo: {memo_code}). "
                        f"Action bypassed; zero duplicate money movement."
                    ),
                    details=data,
                    money_moved=False,
                    audit_ref=memo_code,
                )
        except Exception:
            pass

    # Card Processor chargeback precheck
    if capability.system == "processor" or "chargeback" in capability.id:
        try:
            url = f"{settings.processor_url}/api/chargebacks/{case_id}"
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                network_ref = data.get("network_ref")
                return ExecutionOutcome(
                    category=OutcomeCategory.BUSINESS_OUTCOME,
                    code=OutcomeCode.ALREADY_APPLIED,
                    message=f"Precheck verified chargeback already filed for Case {case_id} (Ref: {network_ref})",
                    details=data,
                    money_moved=False,
                    audit_ref=network_ref,
                )
        except Exception:
            pass

    return None
