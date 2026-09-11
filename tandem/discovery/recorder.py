"""Discovery Trace Recorder.

Captures browser exploration events, DOM candidates, frame contexts,
and container scopes during exploratory UI interactions.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ActionTrace(BaseModel):
    """Represents a single recorded interaction step during UI discovery."""

    step_id: str
    action: str  # NAVIGATE, CLICK, FILL, ASSERT
    semantic_target: str
    selector: str
    locator_candidates: List[str] = Field(default_factory=list)
    frame_selector: Optional[str] = None
    input_name: Optional[str] = None
    concrete_value: Optional[str] = None
    container_selector: Optional[str] = None
    observed_text: Optional[str] = None
    is_mutating: bool = False
    guard_ref: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DiscoveryTrace(BaseModel):
    """Complete trace of an exploratory discovery session ready for compilation."""

    capability_id: str
    version: str = "1.0.0"
    system: str = "core_bank"
    goal: str
    actions: List[ActionTrace] = Field(default_factory=list)
    discovered_memo: Optional[str] = None
    money_moved: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceRecorder:
    """Records browser actions and synthesizes locator candidates."""

    def __init__(
        self,
        capability_id: str,
        goal: str,
        system: str = "core_bank",
    ):
        self.capability_id = capability_id
        self.goal = goal
        self.system = system
        self.actions: List[ActionTrace] = []
        self._step_counter = 0

    def record_navigate(self, url: str) -> ActionTrace:
        self._step_counter += 1
        trace = ActionTrace(
            step_id=f"step_{self._step_counter}_nav",
            action="NAVIGATE",
            semantic_target=url,
            selector=url,
            locator_candidates=[],
            concrete_value=url,
        )
        self.actions.append(trace)
        return trace

    def record_fill(
        self,
        selector: str,
        value: str,
        input_name: Optional[str] = None,
        semantic_target: Optional[str] = None,
        frame_selector: Optional[str] = None,
        locator_candidates: Optional[List[str]] = None,
    ) -> ActionTrace:
        self._step_counter += 1
        candidates = list(locator_candidates or [selector])
        if selector not in candidates:
            candidates.insert(0, selector)

        target_name = semantic_target or f"Input field for {input_name or selector}"
        trace = ActionTrace(
            step_id=f"step_{self._step_counter}_fill_{input_name or 'input'}",
            action="FILL",
            semantic_target=target_name,
            selector=selector,
            locator_candidates=candidates,
            frame_selector=frame_selector,
            input_name=input_name,
            concrete_value=str(value),
        )
        self.actions.append(trace)
        return trace

    def record_click(
        self,
        selector: str,
        semantic_target: Optional[str] = None,
        frame_selector: Optional[str] = None,
        locator_candidates: Optional[List[str]] = None,
        container_selector: Optional[str] = None,
        observed_text: Optional[str] = None,
        is_mutating: bool = False,
        guard_ref: Optional[str] = None,
    ) -> ActionTrace:
        self._step_counter += 1
        candidates = list(locator_candidates or [selector])
        if selector not in candidates:
            candidates.insert(0, selector)

        target_name = semantic_target or f"Click target {selector}"
        trace = ActionTrace(
            step_id=f"step_{self._step_counter}_click",
            action="CLICK",
            semantic_target=target_name,
            selector=selector,
            locator_candidates=candidates,
            frame_selector=frame_selector,
            container_selector=container_selector,
            observed_text=observed_text,
            is_mutating=is_mutating,
            guard_ref=guard_ref,
        )
        self.actions.append(trace)
        return trace

    def finalize(
        self,
        discovered_memo: Optional[str] = None,
        money_moved: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DiscoveryTrace:
        return DiscoveryTrace(
            capability_id=self.capability_id,
            system=self.system,
            goal=self.goal,
            actions=self.actions,
            discovered_memo=discovered_memo,
            money_moved=money_moved,
            metadata=metadata or {},
        )
