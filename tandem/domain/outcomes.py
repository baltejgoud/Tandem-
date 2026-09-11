"""Execution outcome taxonomy and classification for Tandem operations."""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class OutcomeCategory(str, Enum):
    """Broad categorization of an operation's result."""

    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"  # Valid business terminal state (e.g. already credited)
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"  # Technical failure that may be safely retried
    HARD_FAILURE = "HARD_FAILURE"  # Safety violation or guard failure; must halt immediately
    UNCERTAIN_EFFECT = (
        "UNCERTAIN_EFFECT"  # Effect may have occurred; blind retry strictly forbidden
    )


class OutcomeCode(str, Enum):
    """Detailed result codes for execution telemetry and decision routing."""

    # SUCCESS
    COMPLETED = "COMPLETED"

    # BUSINESS_OUTCOME
    ALREADY_APPLIED = "ALREADY_APPLIED"
    DUPLICATE_DISPUTE = "DUPLICATE_DISPUTE"
    TRANSACTION_NOT_FOUND = "TRANSACTION_NOT_FOUND"
    POLICY_DENIED = "POLICY_DENIED"

    # RECOVERABLE_FAILURE
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PAGE_DRIFT = "PAGE_DRIFT"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    TEMPORARY_UNAVAILABLE = "TEMPORARY_UNAVAILABLE"

    # HARD_FAILURE
    ENTITY_BINDING_MISMATCH = "ENTITY_BINDING_MISMATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PRECHECK_UNAVAILABLE = "PRECHECK_UNAVAILABLE"
    POSTCHECK_UNCERTAIN = "POSTCHECK_UNCERTAIN"
    POLICY_VIOLATION = "POLICY_VIOLATION"

    # UNCERTAIN_EFFECT
    UNCERTAIN_EFFECT = "UNCERTAIN_EFFECT"


class ExecutionOutcome(BaseModel):
    """Structured result returned by capability execution and replay."""

    category: OutcomeCategory
    code: OutcomeCode
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    money_moved: bool = False
    audit_ref: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.category == OutcomeCategory.SUCCESS

    @property
    def is_business_terminal(self) -> bool:
        return self.category == OutcomeCategory.BUSINESS_OUTCOME

    @property
    def is_retryable(self) -> bool:
        # UNCERTAIN_EFFECT and HARD_FAILURE must NEVER be blindly retried!
        return self.category == OutcomeCategory.RECOVERABLE_FAILURE

    @property
    def requires_human(self) -> bool:
        return self.category in (OutcomeCategory.HARD_FAILURE, OutcomeCategory.UNCERTAIN_EFFECT)
