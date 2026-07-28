from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Callable

from playwright.async_api import Page

from app.core.models import CrawlerStatus

CLICKABLE_SELECTOR = (
    "a[href], button, [role=button], input[type=submit], input[type=button], "
    "[onclick], [role=link], [role=tab], [role=menuitem]"
)

STUCK_REPEAT_THRESHOLD = 3
MAX_ELEMENTS_PER_PAGE = 40


@dataclass
class WalkerState:
    visited_dom_hashes: set[str] = field(default_factory=set)
    visited_urls: set[str] = field(default_factory=set)
    repeat_counts: dict[str, int] = field(default_factory=dict)
    steps_taken: int = 0


class DomWalker:
    """
    Deterministic BFS/DFS click-walker.

    Falls back to CrawlerStatus.STUCK_AWAITING_INPUT when it can't find a
    safe next action — no LLM involved. The caller (crawl runner) is expected
    to surface that state to the UI, let a human intervene on the same live
    browser session, then call `resume()` to continue autonomous walking
    from wherever the human leaves the page.
    """

    def __init__(
        self,
        page: Page,
        max_steps: int = 200,
        max_depth: int = 15,
        on_status_change: Callable[[CrawlerStatus], None] | None = None,
    ) -> None:
        self.page = page
        self.max_steps = max_steps
        self.max_depth = max_depth
        self.on_status_change = on_status_change
        self.state = WalkerState()
        self.status = CrawlerStatus.AUTONOMOUS
        self._stop_requested = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    def _set_status(self, status: CrawlerStatus) -> None:
        self.status = status
        if self.on_status_change:
            self.on_status_change(status)

    async def _dom_hash(self) -> str:
        html = await self.page.content()
        return hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()

    async def _find_unclicked_element(self):
        elements = await self.page.query_selector_all(CLICKABLE_SELECTOR)
        for el in elements[:MAX_ELEMENTS_PER_PAGE]:
            already_clicked = await el.get_attribute("data-apidiscover-clicked")
            if already_clicked:
                continue
            visible = await el.is_visible()
            if not visible:
                continue
            return el
        return None

    async def run(self) -> None:
        self._set_status(CrawlerStatus.AUTONOMOUS)
        while not self._stop_requested and self.state.steps_taken < self.max_steps:
            await self._resume_event.wait()
            if self._stop_requested:
                break

            dom_hash = await self._dom_hash()
            repeat = self.state.repeat_counts.get(dom_hash, 0)
            self.state.repeat_counts[dom_hash] = repeat + 1

            if repeat + 1 >= STUCK_REPEAT_THRESHOLD:
                await self._go_stuck("Same page state seen repeatedly — likely a loop or dead end")
                continue

            element = await self._find_unclicked_element()
            if element is None:
                await self._go_stuck("No new clickable elements found on this page")
                continue

            try:
                await element.evaluate("(el) => el.setAttribute('data-apidiscover-clicked', '1')")
                async with self.page.expect_navigation(wait_until="domcontentloaded", timeout=3000):
                    await element.click(timeout=2000)
            except Exception:
                try:
                    await element.click(timeout=2000)
                except Exception:
                    continue

            self.state.steps_taken += 1
            self.state.visited_urls.add(self.page.url)

        self._set_status(CrawlerStatus.FINISHED)

    async def _go_stuck(self, reason: str) -> None:
        self._resume_event.clear()
        self._set_status(CrawlerStatus.STUCK_AWAITING_INPUT)
        self.last_stuck_reason = reason

    def resume(self) -> None:
        """Called after a human has manually navigated past a sticking point."""
        self.state.repeat_counts.clear()
        self._resume_event.set()

    def stop(self) -> None:
        self._stop_requested = True
        self._resume_event.set()
