"""Control-scoped identity, account, and monetary guards."""

from typing import Any, Dict, Optional

from tandem.domain.capability import CapabilityDefinition
from tandem.domain.errors import AmountMismatchError, EntityBindingMismatchError
from tandem.domain.money import parse_money
from tandem.surfaces.base import Surface, SurfaceOverlay


def verify_control_scoped_guard(
    capability: CapabilityDefinition,
    inputs: Dict[str, Any],
    surface: Surface,
    frame_selector: Optional[str] = None,
    overlay: Optional[SurfaceOverlay] = None,
) -> None:
    """Verify that the immediate container/row holding the action control binds to expected inputs.

    Rejects whole-page assertions like 'member ID appears somewhere on this page'.
    Reads member ID, account ID, and amount directly from the control's enclosing parent container.
    """
    guard = capability.scoped_guard
    if not guard:
        return

    observed = surface.observe_container(
        container_selector=guard.container_selector,
        frame_selector=frame_selector,
        overlay=overlay,
    )

    expected_member = str(inputs.get("member_id", "")).strip()
    if observed.observed_member_id and expected_member:
        if observed.observed_member_id.strip() != expected_member:
            raise EntityBindingMismatchError(
                f"Control-scoped guard violation: expected member '{expected_member}', "
                f"but observed '{observed.observed_member_id}' inside container '{guard.container_selector}'. "
                f"Transaction aborted to prevent crediting wrong member."
            )

    if "amount" in inputs and observed.observed_amount is not None:
        expected_amount = parse_money(inputs["amount"])
        if observed.observed_amount != expected_amount:
            raise AmountMismatchError(
                f"Control-scoped guard violation: expected amount {expected_amount:.2f}, "
                f"but observed {observed.observed_amount:.2f} inside container."
            )
