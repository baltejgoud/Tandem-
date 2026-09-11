"""Domain models for multi-step cross-system business procedures."""

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ProcedureStepSpec(BaseModel):
    """Specification for a single capability execution within a business procedure."""

    model_config = ConfigDict(extra="forbid")

    step_name: str = Field(description="Logical name of the procedure step")
    capability_id: str = Field(description="ID of the capability to invoke")
    params_template: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary mapping capability inputs to procedure context templates",
    )
    on_failure: str = Field(default="HALT", description="Failure strategy: HALT, RETRY, ESCALATE")


class ProcedureDefinition(BaseModel):
    """Full declarative definition of a multi-system business procedure."""

    model_config = ConfigDict(extra="forbid")

    procedure_id: str = Field(description="Unique procedure identifier, e.g. reg_e_dispute")
    name: str = Field(description="Human readable name")
    description: str = Field(description="Procedure documentation")
    version: str = Field(default="1.0.0")
    steps: List[ProcedureStepSpec] = Field(default_factory=list)
