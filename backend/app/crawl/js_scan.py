from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Page

from app.core.models import CapturedRequest

# Matches quoted strings that look like API paths: start with / (not // which
# is a protocol-relative URL or a comment), at least one more path segment,
# no whitespace/quotes inside. Deliberately conservative — this is meant to
# surface *candidates* for verification, not to be a full JS parser.
PATH_LITERAL_RE = re.compile(r"""['"](/(?!/)[a-zA-Z0-9_\-./{}:]+)['"]""")

# Segments that are almost never real API paths — filters out the heaviest
# source of false positives (asset paths, source-map refs, etc.) without
# trying to be exhaustive.
NOISE_EXTENSIONS = (
    ".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".woff",
    ".woff2", ".ttf", ".ico", ".html",
)
API_HINT_SEGMENTS = ("api", "v1", "v2", "v3", "graphql", "gateway", "rest", "service")


def extract_candidate_paths(js_source: str) -> set[str]:
    candidates: set[str] = set()
    for match in PATH_LITERAL_RE.finditer(js_source):
        path = match.group(1)
        if path.lower().endswith(NOISE_EXTENSIONS):
            continue
        if len(path) < 4 or len(path) > 300:
            continue
        candidates.add(path)
    return candidates


def looks_like_api_path(path: str) -> bool:
    """
    Heuristic filter applied after extraction: paths matching a known API
    hint segment (/api/, /v1/, ...) are far more likely to be real endpoints
    than arbitrary route strings (client-side router paths, i18n keys, etc.).
    Callers may choose to include non-matching paths too, at lower confidence.
    """
    lowered = path.lower()
    return any(f"/{seg}/" in lowered or lowered.startswith(f"/{seg}") for seg in API_HINT_SEGMENTS)


async def discover_script_urls(page: Page) -> set[str]:
    """
    Script URLs referenced by the current page: <script src=...> tags plus,
    for webpack-style apps, chunk filenames referenced in already-loaded
    script text (e.g. a webpack chunk manifest naming other chunk files that
    were never actually requested during this crawl).
    """
    base_url = page.url
    script_srcs = await page.eval_on_selector_all(
        "script[src]", "els => els.map(e => e.getAttribute('src'))"
    )
    urls = {urljoin(base_url, src) for src in script_srcs if src}
    return urls


CHUNK_REF_RE = re.compile(r"""['"]([./a-zA-Z0-9_\-]+\.(?:chunk\.)?js)['"]""")


def extract_chunk_references(js_source: str, base_url: str) -> set[str]:
    """
    Webpack (and similar bundlers) often reference other chunk files as
    string literals, either bare filenames ("vendor.js") or relative paths
    ("./chunks/settings.chunk.js") — both forms are matched and resolved
    against base_url the same way a browser would resolve them.
    """
    refs = set()
    for match in CHUNK_REF_RE.finditer(js_source):
        filename = match.group(1)
        if len(filename) < 5:
            continue
        refs.add(urljoin(base_url, filename))
    return refs


class JsEndpointScanner:
    """
    Static + active JS scanning for candidate API endpoints:
      1. Fetches every <script src> referenced by the current page (not just
         ones the browser happened to request during click-through).
      2. Also follows chunk-filename string references found inside those
         scripts, to reach bundles the initial page never links to directly
         (e.g. lazy-loaded route chunks).
      3. Extracts path-like string literals from all fetched JS source.
      4. Issues a real GET request (through the same authenticated browser
         context) to each candidate, keeping only ones that got a response
         at all — these are returned as CapturedRequest entries tagged via
         resource_type="js_scan_verified" so callers can distinguish them
         from organically-observed traffic.
    """

    def __init__(self, page: Page, max_scripts: int = 40, max_candidates: int = 200):
        self.page = page
        self.max_scripts = max_scripts
        self.max_candidates = max_candidates

    async def _fetch_text(self, url: str) -> str | None:
        try:
            resp = await self.page.request.get(url, timeout=10000)
            if resp.ok:
                return await resp.text()
        except Exception:
            pass
        return None

    async def scan(self) -> list[CapturedRequest]:
        base_url = self.page.url
        script_urls = await discover_script_urls(self.page)

        fetched: dict[str, str] = {}
        queue = list(script_urls)[: self.max_scripts]
        seen = set(queue)

        while queue and len(fetched) < self.max_scripts:
            url = queue.pop(0)
            text = await self._fetch_text(url)
            if text is None:
                continue
            fetched[url] = text

            for ref in extract_chunk_references(text, base_url):
                if ref not in seen and len(seen) < self.max_scripts:
                    seen.add(ref)
                    queue.append(ref)

        candidate_paths: set[str] = set()
        for source in fetched.values():
            candidate_paths |= extract_candidate_paths(source)

        # Prioritize paths matching a known API hint segment — with a hard
        # cap on candidates, these are far more likely to be worth the
        # verification request than an arbitrary /some/client/route string.
        ranked = sorted(candidate_paths, key=lambda p: (not looks_like_api_path(p), p))
        candidates = ranked[: self.max_candidates]

        origin = f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}"
        results: list[CapturedRequest] = []

        for path in candidates:
            url = urljoin(origin, path)
            try:
                resp = await self.page.request.get(url, timeout=8000)
                results.append(
                    CapturedRequest(
                        method="GET",
                        url=url,
                        status_code=resp.status,
                        response_headers=dict(resp.headers),
                        resource_type="js_scan_verified",
                    )
                )
            except Exception:
                continue

        return results
