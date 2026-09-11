"""Playwright implementation of the Surface abstraction."""

import re
from typing import List, Optional

from playwright.sync_api import Locator, Page

from tandem.domain.errors import PageDriftError
from tandem.surfaces.base import (
    ActionEvidence,
    ObservedControl,
    ObservedRecord,
    Surface,
    SurfaceOverlay,
)


class PlaywrightSurface(Surface):
    """Concrete browser surface driver using Playwright with container scoping and drift detection."""

    def __init__(self, page: Page):
        self.page = page
        self.drift_events: List[str] = []

    def _get_context(self, frame_selector: Optional[str] = None):
        """Return the target frame if present, or fallback to top-level page."""
        if frame_selector:
            try:
                if self.page.locator(frame_selector).count() > 0:
                    return self.page.frame_locator(frame_selector)
            except Exception:
                pass
        return self.page

    def _find_best_locator(
        self,
        context,
        candidates: List[str],
        semantic_target: str,
    ) -> tuple[Locator, str]:
        """Try locator candidates sequentially. Record drift if primary candidate fails."""
        for idx, selector in enumerate(candidates):
            try:
                loc = context.locator(selector).first
                timeout = 5000 if idx == 0 else 2000
                if loc.is_visible(timeout=timeout):
                    if idx > 0:
                        drift_msg = (
                            f"Drift detected for '{semantic_target}': primary candidate '{candidates[0]}' "
                            f"failed; matched fallback candidate '{selector}' (rank {idx + 1})"
                        )
                        self.drift_events.append(drift_msg)
                    return loc, selector
            except Exception:
                continue

        raise PageDriftError(
            f"Surface failed to resolve control for '{semantic_target}'. "
            f"Tried candidates: {candidates}"
        )

    def navigate(self, url: str) -> None:
        self.page.goto(url, wait_until="networkidle")

    def resolve_and_click(
        self,
        semantic_target: str,
        candidates: List[str],
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedControl:
        context = self._get_context(frame_selector)
        active_candidates = (
            overlay.get_candidates(semantic_target, candidates) if overlay else candidates
        )
        loc, selector = self._find_best_locator(context, active_candidates, semantic_target)

        text = (loc.text_content() or "").strip()
        tag = loc.evaluate("el => el.tagName.toLowerCase()") or "element"
        is_enabled = loc.is_enabled()

        loc.click()
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        return ObservedControl(
            name=semantic_target,
            resolved_selector=selector,
            tag_name=tag,
            text_content=text,
            is_enabled=is_enabled,
            is_visible=True,
        )

    def resolve_and_fill(
        self,
        semantic_target: str,
        candidates: List[str],
        value: str,
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedControl:
        context = self._get_context(frame_selector)
        active_candidates = (
            overlay.get_candidates(semantic_target, candidates) if overlay else candidates
        )
        loc, selector = self._find_best_locator(context, active_candidates, semantic_target)

        loc.fill(value)

        return ObservedControl(
            name=semantic_target,
            resolved_selector=selector,
            tag_name="input",
            text_content=value,
            is_enabled=loc.is_enabled(),
            is_visible=True,
        )

    def observe_container(
        self,
        container_selector: str,
        frame_selector: Optional[str] = None,
        overlay: Optional[SurfaceOverlay] = None,
    ) -> ObservedRecord:
        context = self._get_context(frame_selector)
        active_selector = (
            overlay.container_overrides.get(container_selector, container_selector)
            if overlay
            else container_selector
        )

        container_loc = context.locator(active_selector).first
        try:
            container_loc.wait_for(state="visible", timeout=5000)
        except Exception:
            raise PageDriftError(f"Container element '{active_selector}' not visible on surface")

        raw_text = container_loc.inner_text() or ""

        # Extract scoped elements within this container only
        observed_member = None
        observed_account = None
        observed_amount = None
        observed_case = None

        # Try data attributes
        try:
            data_member = container_loc.get_attribute("data-member-id")
            if data_member:
                observed_member = data_member.strip()
        except Exception:
            pass

        try:
            data_amt = container_loc.get_attribute("data-amount")
            if data_amt:
                observed_amount = float(data_amt.replace("$", "").replace(",", "").strip())
        except Exception:
            pass

        # Try scoped CSS classes within container
        if not observed_member:
            m_loc = container_loc.locator(".scoped-member-id").first
            if m_loc.count() > 0:
                observed_member = m_loc.text_content().strip()

        if not observed_account:
            a_loc = container_loc.locator(".scoped-account-id").first
            if a_loc.count() > 0:
                observed_account = a_loc.text_content().strip()

        if observed_amount is None:
            amt_loc = container_loc.locator(".scoped-amount").first
            if amt_loc.count() > 0:
                amt_str = amt_loc.text_content().strip()
                # Parse monetary float, e.g. "$340.00 USD" -> 340.0
                match = re.search(r"(\d+(?:\.\d{2})?)", amt_str)
                if match:
                    observed_amount = float(match.group(1))

        if not observed_case:
            case_loc = container_loc.locator(".scoped-case-id").first
            if case_loc.count() > 0:
                observed_case = case_loc.text_content().strip()

        return ObservedRecord(
            container_selector=active_selector,
            observed_member_id=observed_member,
            observed_account_id=observed_account,
            observed_amount=observed_amount,
            observed_case_id=observed_case,
            raw_text=raw_text,
        )

    def capture_evidence(self, step_id: str) -> ActionEvidence:
        screenshot = self.page.screenshot(full_page=True)
        content = self.page.content()
        return ActionEvidence(
            step_id=step_id,
            screenshot_bytes=screenshot,
            dom_snapshot=content,
        )
