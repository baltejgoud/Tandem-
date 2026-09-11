"""Surface abstractions decoupling business capabilities from DOM selectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from tandem.domain.money import Money


class LocatorKind(str, Enum):
    CSS = "CSS"
    TEXT = "TEXT"
    ROLE = "ROLE"
    XPATH = "XPATH"
    CONTAINER_RELATIVE = "CONTAINER_RELATIVE"


@dataclass
class ObservedControl:
    """Represents an actionable control inspected on the current surface."""

    name: str
    resolved_selector: str
    tag_name: str
    text_content: Optional[str] = None
    is_enabled: bool = True
    is_visible: bool = True


@dataclass
class ObservedRecord:
    """Logical record extracted from a parent container or row enclosing a control."""

    container_selector: str
    observed_member_id: Optional[str] = None
    observed_account_id: Optional[str] = None
    observed_amount: Optional[Money] = None
    observed_currency: Optional[str] = None
    observed_case_id: Optional[str] = None
    raw_text: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class ActionEvidence:
    """Audit evidence captured before or after an action execution."""

    step_id: str
    screenshot_bytes: Optional[bytes] = None
    dom_snapshot: Optional[str] = None
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SurfaceOverlay:
    """Per-institution surface overlay mapping semantic targets to institution-specific selectors."""

    institution_id: str
    name: str
    selector_overrides: Dict[str, List[str]] = field(default_factory=dict)
    container_overrides: Dict[str, str] = field(default_factory=dict)
    drift_warnings: List[str] = field(default_factory=list)

    def get_candidates(self, semantic_target: str, default_candidates: List[str]) -> List[str]:
        """Return overlay candidates if present, falling back to base candidates."""
        if semantic_target in self.selector_overrides:
            return self.selector_overrides[semantic_target]
        return default_candidates


class Surface(ABC):
    """Abstract surface interface separating replay logic from underlying automation driver."""

    @abstractmethod
    def navigate(self, url: str) -> None:
        pass

    @abstractmethod
    def resolve_and_click(
        self,
        semantic_target: str,
        candidates: List[str],
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedControl:
        pass

    @abstractmethod
    def resolve_and_fill(
        self,
        semantic_target: str,
        candidates: List[str],
        value: str,
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedControl:
        pass

    @abstractmethod
    def observe_container(
        self,
        container_selector: str,
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedRecord:
        pass

    @abstractmethod
    def capture_evidence(self, step_id: str) -> ActionEvidence:
        pass
