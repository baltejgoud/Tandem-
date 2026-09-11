"""Capability Artifact Compiler.

Transforms exploratory DiscoveryTrace sessions into deterministic, versioned,
typed CapabilityDefinition YAML artifacts equipped with:
- Abstracted input templates
- Typed effect classification (COMMIT/READ)
- Container-scoped identity guards
- Precheck and postcheck definitions
- Bounded safety constraints
- Cryptographic SHA-256 artifact verification
"""

import hashlib
from pathlib import Path
from typing import Optional, Tuple
import yaml

from tandem.discovery.recorder import DiscoveryTrace
from tandem.domain.capability import (
    CapabilityDefinition,
    ScopedGuardSpec,
    StepDefinition,
)
from tandem.domain.effects import (
    BoundsSpec,
    EffectClass,
    EffectIdentitySpec,
    EffectSpec,
    PostcheckSpec,
    PrecheckSpec,
)


class CapabilityCompiler:
    """Compiles recorded discovery traces into executable capability artifacts."""

    def __init__(self, output_dir: str = "capabilities/compiled"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(
        self,
        trace: DiscoveryTrace,
        target_filename: Optional[str] = None,
    ) -> Tuple[CapabilityDefinition, Path]:
        """Compile a DiscoveryTrace into a validated CapabilityDefinition YAML artifact."""
        steps = []
        for action in trace.actions:
            step_dict = {
                "step_id": action.step_id,
                "action": action.action,
                "semantic_target": action.semantic_target,
                "locator_candidates": action.locator_candidates,
                "frame_selector": action.frame_selector,
            }

            if action.action == "FILL" and action.input_name:
                step_dict["input_value_template"] = f"{{{{input.{action.input_name}}}}}"

            steps.append(StepDefinition(**step_dict))

        # Effect metadata synthesis
        effect_spec = EffectSpec(
            effect_class=EffectClass.COMMIT if trace.money_moved else EffectClass.READ,
            idempotency_key="regE:{{input.case_id}}:provisional_credit",
            identity=EffectIdentitySpec(
                institution_id="{{input.institution_id}}",
                procedure_id="reg_e_dispute",
                case_id="{{input.case_id}}",
                capability_id=trace.capability_id,
                member_id="{{input.member_id}}",
                account_id="{{input.account_id}}",
                amount="{{input.amount}}",
                currency="{{input.currency}}",
                business_reference="{{input.case_id}}",
            ),
            precheck=PrecheckSpec(
                capability="core.find_memo_by_case",
                params={"case_id": "{{input.case_id}}"},
                if_found="ALREADY_APPLIED",
            ),
            postcheck=PostcheckSpec(
                capability="core.find_memo_by_case",
                params={"case_id": "{{input.case_id}}"},
                expected_status="CONFIRMED",
            ),
            compensation="core.reverse_provisional_credit",
            bounds=BoundsSpec(max_amount=500.00, currency="USD"),
        )

        scoped_guard = ScopedGuardSpec(
            container_selector="#credit_action_container, .confirm-panel",
            expected_member_template="{{input.member_id}}",
            expected_amount_template="{{input.amount}}",
            expected_case_template="{{input.case_id}}",
        )

        input_schema = {
            "type": "object",
            "properties": {
                "member_id": {"type": "string"},
                "account_id": {"type": "string"},
                "case_id": {"type": "string"},
                "amount": {"type": "number"},
                "currency": {"type": "string", "const": "USD"},
                "institution_id": {"type": "string"},
            },
            "required": [
                "institution_id",
                "member_id",
                "account_id",
                "case_id",
                "amount",
                "currency",
            ],
        }

        # Build definition
        capability = CapabilityDefinition(
            id=trace.capability_id,
            version=trace.version,
            name="Post Provisional Credit",
            description=trace.goal,
            system=trace.system,
            effect=effect_spec,
            input_schema=input_schema,
            scoped_guard=scoped_guard,
            steps=steps,
        )

        # Serialize to YAML (using aliases and json mode so Enums serialize as strings)
        raw_dict = capability.model_dump(
            by_alias=True, mode="json", exclude={"artifact_hash"}
        )
        yaml_content = yaml.dump(raw_dict, sort_keys=False)

        # Compute SHA-256 artifact hash
        artifact_hash = hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()
        capability.artifact_hash = artifact_hash

        filename = target_filename or f"{trace.capability_id.replace('.', '_')}.yaml"
        output_file = self.output_dir / filename

        # Add comment header with hash
        header = f"# Compiled by Tandem CapabilityCompiler\n# SHA-256: {artifact_hash}\n\n"
        output_file.write_text(header + yaml_content, encoding="utf-8")

        return capability, output_file
