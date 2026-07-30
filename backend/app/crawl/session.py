from __future__ import annotations

import uuid
from typing import Callable

from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.models import CapturedRequest, CrawlerStatus
from app.crawl.container import VncBrowserContainer
from app.crawl.js_scan import JsEndpointScanner
from app.export.normalize import templatize_path


class CrawlSession:
    """
    Owns one VNC browser container + the Playwright connection into it for a
    single crawl run.

    A human drives the browser directly through noVNC (served by the
    container) — real X11 input, no CDP input-forwarding quirks. The backend
    drives the SAME browser autonomously via `connect_over_cdp` once the
    walker takes over; control just switches which side is "allowed" to act,
    the browser/context/cookies never change.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.status: CrawlerStatus = CrawlerStatus.IDLE
        self.captured: list[CapturedRequest] = []
        self._on_capture: Callable[[CapturedRequest], None] | None = None

        # Session-scoped exclusions: hosts excluded entirely, or specific
        # (method, host, normalized-path) endpoints excluded individually.
        # Checked both going forward (stop recording matches) and applied
        # again at view/export time (covers excluding something already
        # captured earlier in the same session).
        self.excluded_hosts: set[str] = set()
        self.excluded_endpoints: set[tuple[str, str, str]] = set()

        self.container = VncBrowserContainer(container_name=f"apidiscover-crawl-{session_id}")
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        assert self._page is not None, "session not started"
        return self._page

    @property
    def novnc_url(self) -> str:
        return self.container.novnc_url

    async def start(self, start_url: str, storage_state: dict | None = None) -> None:
        await self.container.start()

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.container.cdp_endpoint)

        # The container's Chrome starts with one default context/page already open.
        self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        if storage_state:
            await self._context.add_cookies(storage_state.get("cookies", []))
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        self._page.on("response", self._handle_response)
        await self._page.goto(start_url, wait_until="domcontentloaded")

        self.status = CrawlerStatus.MANUAL_CONTROL

    def _is_excluded(self, method: str, url: str) -> bool:
        parts = urlsplit(url)
        if parts.netloc in self.excluded_hosts:
            return True
        templated_path, _ = templatize_path(parts.path)
        return (method.upper(), parts.netloc, templated_path) in self.excluded_endpoints

    def exclude_host(self, host: str) -> None:
        self.excluded_hosts.add(host)
        self.captured = [c for c in self.captured if urlsplit(c.url).netloc != host]

    def exclude_endpoint(self, method: str, host: str, path_template: str) -> None:
        self.excluded_endpoints.add((method.upper(), host, path_template))

        def matches(c: CapturedRequest) -> bool:
            parts = urlsplit(c.url)
            templated_path, _ = templatize_path(parts.path)
            return c.method.upper() == method.upper() and parts.netloc == host and templated_path == path_template

        self.captured = [c for c in self.captured if not matches(c)]

    def _handle_response(self, response) -> None:
        import asyncio

        request = response.request
        if request.resource_type not in ("xhr", "fetch", "document"):
            return
        if self._is_excluded(request.method, request.url):
            return

        async def _record() -> None:
            try:
                body_sample = None
                try:
                    text = await response.text()
                    body_sample = text[:2000]
                except Exception:
                    pass
                captured = CapturedRequest(
                    method=request.method,
                    url=request.url,
                    request_headers=await request.all_headers(),
                    request_body=request.post_data,
                    status_code=response.status,
                    response_headers=dict(response.headers),
                    response_body_sample=body_sample,
                    resource_type=request.resource_type,
                )
                self.captured.append(captured)
                if self._on_capture:
                    self._on_capture(captured)
            except Exception:
                pass

        asyncio.create_task(_record())

    def set_capture_handler(self, handler: Callable[[CapturedRequest], None]) -> None:
        self._on_capture = handler

    async def run_js_scan(self) -> list[CapturedRequest]:
        """
        On-demand pass: fetch JS bundles referenced by the current page (plus
        chunks they reference in turn), extract candidate endpoint paths, and
        verify each with a real request through the same authenticated
        browser context. Results are appended to `captured` (tagged
        resource_type="js_scan_verified") and streamed via the capture
        handler like any other capture, but excluded hosts/endpoints are
        respected — a candidate matching an active exclusion is dropped
        rather than resurfacing it.
        """
        scanner = JsEndpointScanner(self.page)
        results = await scanner.scan()

        kept: list[CapturedRequest] = []
        for cap in results:
            if self._is_excluded(cap.method, cap.url):
                continue
            self.captured.append(cap)
            kept.append(cap)
            if self._on_capture:
                self._on_capture(cap)

        return kept

    async def export_storage_state(self) -> dict:
        assert self._context is not None
        return await self._context.storage_state()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await self.container.stop()
        self.status = CrawlerStatus.FINISHED


_sessions: dict[str, CrawlSession] = {}


def create_session() -> CrawlSession:
    session_id = str(uuid.uuid4())
    session = CrawlSession(session_id)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> CrawlSession | None:
    return _sessions.get(session_id)


def remove_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
