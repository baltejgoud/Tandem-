"""Postcheck execution to verify effect landed on target system."""

from typing import Any, Dict, Optional

import httpx

from tandem.config import settings
from tandem.domain.capability import CapabilityDefinition
from tandem.domain.outcomes import ExecutionOutcome, OutcomeCategory, OutcomeCode


def execute_postcheck(
    capability: CapabilityDefinition, inputs: Dict[str, Any]
) -> Optional[ExecutionOutcome]:
    """Execute postcheck against target legacy system to verify whether effect landed."""
    case_id = inputs.get("case_id")
    if not case_id:
        return None

    # Core Banking postcheck
    if capability.system == "core_bank" or "provisional_credit" in capability.id:
        try:
            url = f"{settings.core_bank_url}/api/credits/{case_id}"
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                return ExecutionOutcome(
                    category=OutcomeCategory.SUCCESS,
                    code=OutcomeCode.COMPLETED,
                    message=f"Postcheck verified provisional credit applied (Memo: {data.get('memo_code')})",
                    details=data,
                    money_moved=True,
                    audit_ref=data.get("memo_code"),
                )
        except Exception:
            pass

    # Processor postcheck
    if capability.system == "processor" or "chargeback" in capability.id:
        try:
            url = f"{settings.processor_url}/api/chargebacks/{case_id}"
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                return ExecutionOutcome(
                    category=OutcomeCategory.SUCCESS,
                    code=OutcomeCode.COMPLETED,
                    message=f"Postcheck verified chargeback filed on network (Ref: {data.get('network_ref')})",
                    details=data,
                    money_moved=False,
                    audit_ref=data.get("network_ref"),
                )
        except Exception:
            pass

    # Documents postcheck
    if capability.system == "documents" or "notice" in capability.id:
        try:
            url = f"{settings.documents_url}/api/notices/{case_id}"
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                return ExecutionOutcome(
                    category=OutcomeCategory.SUCCESS,
                    code=OutcomeCode.COMPLETED,
                    message=f"Postcheck verified notice dispatched (Notice ID: {data.get('notice_id')})",
                    details=data,
                    money_moved=False,
                    audit_ref=data.get("notice_id"),
                )
        except Exception:
            pass

    return None
