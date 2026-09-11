"""Reconciliation engine for ambiguous execution and uncertain effects."""

from typing import Any, Dict

from tandem.domain.capability import CapabilityDefinition
from tandem.domain.outcomes import ExecutionOutcome, ExecutionPhase, OutcomeCategory, OutcomeCode
from tandem.replay.postcheck import execute_postcheck


def reconcile_commit_execution(
    capability: CapabilityDefinition,
    inputs: Dict[str, Any],
    error_message: str = "",
) -> ExecutionOutcome:
    """Reconcile ambiguous execution state when a network or browser exception occurs during a COMMIT.

    SAFETY INVARIANT: An uncertain effect MUST NEVER be blindly retried!
    1. Perform postcheck inquiry against the target system.
    2. If postcheck proves the mutation completed -> resolve as SUCCESS with audit reference.
    3. If postcheck is inconclusive -> classify as UNCERTAIN_EFFECT and escalate to human.
    """
    postcheck_result = execute_postcheck(capability, inputs)
    if postcheck_result.is_success:
        return ExecutionOutcome(
            category=OutcomeCategory.SUCCESS,
            code=OutcomeCode.CONFIRMED_APPLIED,
            message=(
                f"Reconciliation successful: Postcheck confirmed effect occurred despite "
                f"interrupted connection. (Ref: {postcheck_result.audit_ref})"
            ),
            details={
                "reconciled": True,
                "postcheck_details": postcheck_result.details,
                "original_error": error_message,
            },
            money_moved=postcheck_result.money_moved,
            audit_ref=postcheck_result.audit_ref,
            execution_phase=ExecutionPhase.SUBMIT_CONFIRMED,
        )

    if postcheck_result.code == OutcomeCode.CONFIRMED_NOT_APPLIED:
        return postcheck_result.model_copy(
            update={
                "details": {
                    **postcheck_result.details,
                    "safe_to_retry": True,
                    "original_error": error_message,
                },
                "execution_phase": ExecutionPhase.AFTER_SUBMIT_UNKNOWN,
            }
        )

    # Inconclusive: effect status cannot be proven
    return ExecutionOutcome(
        category=OutcomeCategory.UNCERTAIN_EFFECT,
        code=OutcomeCode.UNCERTAIN_EFFECT,
        message=(
            f"CRITICAL SAFETY EXCEPTION: COMMIT operation '{capability.id}' encountered an interruption: "
            f"'{error_message}'. Postcheck could not confirm state. Automatic retry is strictly forbidden "
            f"to prevent duplicate money movement. Case requires manual human investigation."
        ),
        details={
            "capability_id": capability.id,
            "inputs": inputs,
            "original_error": error_message,
            "postcheck_code": postcheck_result.code.value,
        },
        money_moved=False,
        execution_phase=ExecutionPhase.AFTER_SUBMIT_UNKNOWN,
    )
