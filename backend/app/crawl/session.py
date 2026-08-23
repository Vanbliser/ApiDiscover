from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Callable

from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.config import get_proxy_ca_cert_path
from app.core.models import CapturedRequest, CrawlerStatus
from app.crawl.capture_poller import CapturePoller
from app.crawl.container import VncBrowserContainer
from app.crawl.js_scan import JsEndpointScanner
from app.export.normalize import templatize_path

# Per-session scratch space for files uploaded from the browser client and
# bind-mounted into the session's container (see VncBrowserContainer). Lives
# under backend/data alongside the other gitignored local state
# (provider_config.enc, secret.key).
UPLOADS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"

# Preset extension groups for the "exclude static files" quick-toggle — each
# key is one chip in the UI; STATIC_FILE_EXTENSIONS is the flat set used to
# turn the whole preset on/off in one action. Matched against the URL path's
# suffix, not Content-Type, since exclusion is decided before/independent of
# any response and query strings/fragments never affect a file extension.
STATIC_FILE_EXTENSION_GROUPS: dict[str, set[str]] = {
    "css": {"css"},
    "html": {"html", "htm"},
    "js": {"js", "mjs"},
    "images": {"svg", "webp", "ico", "png", "jpg", "jpeg", "gif", "bmp", "avif"},
    "fonts": {"woff", "woff2", "ttf", "otf", "eot"},
}
STATIC_FILE_EXTENSIONS: frozenset[str] = frozenset(
    ext for group in STATIC_FILE_EXTENSION_GROUPS.values() for ext in group
)


def _path_extension(path: str) -> str:
    """Lowercased extension with no leading dot, or "" if the path has none."""
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return ""
    return last_segment.rsplit(".", 1)[-1].lower()


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

    def __init__(self, session_id: str, proxy_server: str | None = None) -> None:
        self.session_id = session_id
        self.status: CrawlerStatus = CrawlerStatus.IDLE
        self.captured: list[CapturedRequest] = []
        self._on_capture: Callable[[CapturedRequest], None] | None = None

        # Session-scoped exclusions: hosts excluded entirely, specific
        # (method, host, normalized-path) endpoints excluded individually,
        # file extensions (e.g. "css", "png" — for filtering out static
        # assets as a category rather than one by one), and HTTP methods
        # (e.g. "OPTIONS" — CORS preflights are the common case, never real
        # API surface to document). Checked both going forward (suppresses
        # the live capture-count stream) and applied again at view/export
        # time (covers something already captured before the exclusion was
        # set) — see visible_captures.
        self.excluded_hosts: set[str] = set()
        self.excluded_endpoints: set[tuple[str, str, str]] = set()
        self.excluded_extensions: set[str] = set()
        self.excluded_methods: set[str] = set()

        self.uploads_dir = UPLOADS_ROOT / session_id
        # Both decided once, here, and fixed for the container's whole life:
        # a CA cert uploaded in Settings after this session's container has
        # already started won't retroactively apply (NSS import happens
        # once at Chrome's first launch — see start-browser.sh), and neither
        # will a proxy target chosen after start() — changing either means
        # starting a new session.
        self.container = VncBrowserContainer(
            container_name=f"apidiscover-crawl-{session_id}",
            uploads_dir=str(self.uploads_dir),
            proxy_ca_cert_path=get_proxy_ca_cert_path(),
            proxy_server=proxy_server,
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._capture_poller: CapturePoller | None = None

    @property
    def page(self) -> Page:
        assert self._page is not None, "session not started"
        return self._page

    @property
    def novnc_url(self) -> str:
        return self.container.novnc_url

    @property
    def has_proxy_ca_cert(self) -> bool:
        return self.container.proxy_ca_cert_path is not None

    @property
    def proxy_server(self) -> str | None:
        return self.container.proxy_server

    async def start(self, start_url: str, storage_state: dict | None = None) -> None:
        # Must exist before `docker run` so the bind mount has something to
        # attach to — Docker would otherwise create it itself as root-owned,
        # which works too, but creating it explicitly keeps ownership/cleanup
        # unambiguous on the backend side.
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        await self.container.start()

        # Capture starts polling immediately, before Playwright even attaches
        # — mitmproxy (see vnc-browser/capture_addon.py) is the actual
        # capture point now, not page.on("response"), specifically because
        # it sees every request Chrome sends regardless of whether/when
        # Playwright's CDP session has attached, and regardless of manual vs.
        # autonomous control. Playwright below is only used to drive
        # navigation and the autonomous walker.
        self._capture_poller = CapturePoller(self.container.capture_api_endpoint, self._handle_capture)
        self._capture_poller.start()

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.container.cdp_endpoint)

        # The container's Chrome starts with one default context/page already open.
        self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        if storage_state:
            await self._context.add_cookies(storage_state.get("cookies", []))
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        await self._page.goto(start_url, wait_until="domcontentloaded")

        self.status = CrawlerStatus.MANUAL_CONTROL

    def _is_excluded(self, method: str, url: str) -> bool:
        if method.upper() in self.excluded_methods:
            return True
        parts = urlsplit(url)
        if parts.netloc in self.excluded_hosts:
            return True
        if _path_extension(parts.path) in self.excluded_extensions:
            return True
        templated_path, _ = templatize_path(parts.path)
        return (method.upper(), parts.netloc, templated_path) in self.excluded_endpoints

    def visible_captures(self) -> list[CapturedRequest]:
        """
        `self.captured` keeps every request ever seen, excluded or not —
        exclusion is metadata (excluded_hosts/excluded_endpoints), not
        deletion, specifically so re-including a host or endpoint can
        instantly restore everything captured while it was excluded rather
        than only resuming capture of new matching requests. Both the live
        endpoints view and the export go through this instead of touching
        `captured` directly, so they can never drift out of sync with the
        current exclusion state.
        """
        return [c for c in self.captured if not self._is_excluded(c.method, c.url)]

    def exclude_host(self, host: str) -> None:
        self.excluded_hosts.add(host)

    def include_host(self, host: str) -> None:
        self.excluded_hosts.discard(host)

    def exclude_endpoint(self, method: str, host: str, path_template: str) -> None:
        self.excluded_endpoints.add((method.upper(), host, path_template))

    def include_endpoint(self, method: str, host: str, path_template: str) -> None:
        self.excluded_endpoints.discard((method.upper(), host, path_template))

    def exclude_extension(self, extension: str) -> None:
        self.excluded_extensions.add(extension.lower().lstrip("."))

    def include_extension(self, extension: str) -> None:
        self.excluded_extensions.discard(extension.lower().lstrip("."))

    def exclude_method(self, method: str) -> None:
        self.excluded_methods.add(method.upper())

    def include_method(self, method: str) -> None:
        self.excluded_methods.discard(method.upper())

    def _handle_capture(self, captured: CapturedRequest) -> None:
        # No resource_type filter here, unlike the old Playwright-based path
        # — mitmproxy has no notion of it (it operates below the browser
        # entirely) and deliberately captures every HTTP(S) request Chrome
        # sends, which is the whole point of moving capture here.
        #
        # Always appended, even if currently excluded — exclusion is a view
        # filter (see visible_captures), not deletion, so re-including a
        # host/endpoint later can restore everything captured while it was
        # excluded. The live capture-count stream is still suppressed for
        # excluded traffic, though, so the UI doesn't count requests the
        # user has asked to not see.
        self.captured.append(captured)
        if self._is_excluded(captured.method, captured.url):
            return
        if self._on_capture:
            self._on_capture(captured)

    def set_capture_handler(self, handler: Callable[[CapturedRequest], None]) -> None:
        self._on_capture = handler

    async def run_js_scan(self) -> list[CapturedRequest]:
        """
        On-demand pass: fetch JS bundles referenced by the current page (plus
        chunks they reference in turn), extract candidate endpoint paths, and
        verify each with a real request through the same authenticated
        browser context. Results are appended to `captured` (tagged
        resource_type="js_scan_verified") regardless of exclusion state,
        same as live captures (see _handle_capture) so a re-include later
        can recover them, but a candidate matching an active exclusion is
        left out of the returned/streamed set so it doesn't resurface while
        still excluded.
        """
        scanner = JsEndpointScanner(self.page)
        results = await scanner.scan()

        kept: list[CapturedRequest] = []
        for cap in results:
            self.captured.append(cap)
            if self._is_excluded(cap.method, cap.url):
                continue
            kept.append(cap)
            if self._on_capture:
                self._on_capture(cap)

        return kept

    async def export_storage_state(self) -> dict:
        assert self._context is not None
        return await self._context.storage_state()

    async def stop(self) -> None:
        if self._capture_poller:
            await self._capture_poller.stop()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await self.container.stop()
        # The bind mount is a host-side directory independent of the
        # container's own --rm teardown, so it needs its own cleanup —
        # uploaded files must not outlive the session.
        shutil.rmtree(self.uploads_dir, ignore_errors=True)
        self.status = CrawlerStatus.FINISHED


_sessions: dict[str, CrawlSession] = {}


def create_session(proxy_server: str | None = None) -> CrawlSession:
    session_id = str(uuid.uuid4())
    session = CrawlSession(session_id, proxy_server=proxy_server)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> CrawlSession | None:
    return _sessions.get(session_id)


def remove_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
