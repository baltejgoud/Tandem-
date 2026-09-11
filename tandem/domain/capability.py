"""Capability artifact schema and typed execution definitions."""

import hashlib
import json
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tandem.domain.effects import EffectClass, EffectSpec


class StepAction(str, Enum):
    """Supported deterministic browser interaction primitives."""

    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    FILL = "FILL"
    SELECT_FRAME = "SELECT_FRAME"
    WAIT_FOR = "WAIT_FOR"
    ASSERT_CONTAINER = "ASSERT_CONTAINER"
    READ_TEXT = "READ_TEXT"


class StepDefinition(BaseModel):
    """A single deterministic browser interaction step within a capability."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="Unique step identifier within the capability")
    action: StepAction = Field(description="Action primitive to execute")
    semantic_target: str = Field(description="Human/business description of the target element")
    locator_candidates: List[str] = Field(
        default_factory=list,
        description="Ordered list of robust locator strategies (CSS, text, XPath, role)",
    )
    input_value_template: Optional[str] = Field(
        default=None, description="Template string for input values, e.g. {{input.amount}}"
    )
    expected_text: Optional[str] = Field(
        default=None, description="Expected text content for verification steps"
    )
    frame_selector: Optional[str] = Field(
        default=None, description="Selector of parent iframe if nested inside a frame"
    )


class ScopedGuardSpec(BaseModel):
    """Control-scoped guard specification ensuring action is bound to the correct entity."""

    model_config = ConfigDict(extra="forbid")

    container_selector: str = Field(
        description="Selector for the enclosing row, card, or panel holding the submit control"
    )
    expected_member_template: str = Field(
        default="{{input.member_id}}",
        description="Template for expected submitted member ID",
    )
    expected_account_template: str = Field(
        default="{{input.account_id}}",
        description="Template for expected submitted account ID",
    )
    expected_amount_template: str = Field(
        default="{{input.amount}}",
        description="Template for expected submitted monetary amount",
    )
    expected_currency_template: str = Field(
        default="{{input.currency}}",
        description="Template for expected submitted ISO currency",
    )
    expected_case_template: str = Field(
        default="{{input.case_id}}",
        description="Template for expected submitted case/dispute reference",
    )
    expected_institution_template: str = Field(
        default="{{input.institution_id}}",
        description="Template for expected submitted institution ID",
    )


class CapabilityDefinition(BaseModel):
    """Versioned, typed capability artifact compiled from discovery or manually specified."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(description="Unique capability identifier, e.g. core.post_provisional_credit")
    version: str = Field(default="1.0.0", description="Semantic version of capability artifact")
    name: str = Field(description="Descriptive name")
    description: str = Field(description="Purpose of capability")
    system: str = Field(description="Target system key: core_bank, processor, documents")
    effect: EffectSpec = Field(description="Effect contract and safety metadata")
    input_schema: Dict[str, Any] = Field(description="JSON schema for input arguments")
    output_schema: Dict[str, Any] = Field(
        default_factory=dict, description="JSON schema for outputs"
    )
    scoped_guard: Optional[ScopedGuardSpec] = Field(
        default=None, description="Container-scoped identity and amount guard"
    )
    steps: List[StepDefinition] = Field(
        default_factory=list, description="Deterministic browser interaction steps"
    )
    source_discovery_run_id: Optional[str] = Field(
        default=None, description="ID of discovery run that generated this artifact"
    )
    artifact_hash: Optional[str] = Field(
        default=None, description="SHA-256 hash of capability definition for integrity"
    )

    @model_validator(mode="after")
    def validate_capability_safety(self) -> "CapabilityDefinition":
        # COMMIT capabilities MUST have a scoped guard!
        if self.effect.effect_class == EffectClass.COMMIT:
            if not self.scoped_guard:
                raise ValueError(
                    f"Capability '{self.id}' has COMMIT effect but lacks a scoped_guard. "
                    f"All COMMIT operations require container-scoped identity verification."
                )
        return self

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 digest of capability configuration."""
        data = {
            "id": self.id,
            "version": self.version,
            "system": self.system,
            "effect": self.effect.model_dump(by_alias=True, mode="json"),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "steps": [s.model_dump(mode="json") for s in self.steps],
            "scoped_guard": (
                self.scoped_guard.model_dump(mode="json") if self.scoped_guard else None
            ),
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_capability_from_yaml(path: str) -> CapabilityDefinition:
    """Load and validate a capability definition from a YAML file."""
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cap = CapabilityDefinition.model_validate(data)
    cap.artifact_hash = cap.compute_hash()
    return cap
