from __future__ import annotations

import re
from urllib.parse import urlsplit, parse_qsl

from app.core.models import CapturedRequest, CrawlEndpoint

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
NUMERIC_RE = re.compile(r"^\d+$")


def templatize_path(path: str) -> tuple[str, list[str]]:
    """Replace path segments that look like IDs with named placeholders."""
    segments = path.split("/")
    path_params: list[str] = []
    templated: list[str] = []

    for seg in segments:
        if not seg:
            templated.append(seg)
            continue
        if NUMERIC_RE.match(seg):
            param_name = f"id{len(path_params) + 1}"
            path_params.append(param_name)
            templated.append(f"{{{param_name}}}")
        elif UUID_RE.match(seg):
            param_name = f"{'uuid' if not path_params else 'uuid' + str(len(path_params) + 1)}"
            path_params.append(param_name)
            templated.append(f"{{{param_name}}}")
        else:
            templated.append(seg)

    return "/".join(templated), path_params


def normalize_captures(captures: list[CapturedRequest]) -> list[CrawlEndpoint]:
    """
    Dedupe and normalize raw captured requests into endpoint entries:
    - group by (method, host, templated path)
    - collect query params and status codes seen across repeats
    - an endpoint that's ever been organically observed keeps
      discovery_source="observed" even if a JS-scan verification request for
      the same endpoint is processed too — observed traffic is the stronger
      signal and shouldn't be downgraded by a later/earlier scan result.

    Every capture is kept regardless of resource_type: real captures come
    from mitmproxy (see capture_addon.py), which has no notion of
    Playwright's resourceType at all (resource_type is always None) since it
    operates below the browser entirely — that's deliberate, so every
    HTTP(S) request Chrome sends is included here, not just XHR/fetch calls.
    resource_type is only ever non-None for JS-scan-verified results
    (see js_scan.py), which is why that's the one value checked explicitly.
    """
    by_key: dict[tuple[str, str, str], CrawlEndpoint] = {}
    # Tracks which distinct query-value combinations have already been added
    # to each endpoint's example_requests, so repeats with the exact same
    # values (not just the same param names) don't pile up duplicate items —
    # sorted so param order in the URL doesn't create false distinctions.
    seen_variants: dict[tuple[str, str, str], set[tuple[tuple[str, str], ...]]] = {}

    for cap in captures:
        source = "js_scan_verified" if cap.resource_type == "js_scan_verified" else "observed"

        parts = urlsplit(cap.url)
        templated_path, path_params = templatize_path(parts.path)
        query_pairs = parse_qsl(parts.query)
        query_params = sorted({k for k, _ in query_pairs})
        variant_key = tuple(sorted(query_pairs))

        key = (cap.method.upper(), parts.netloc, templated_path)
        existing = by_key.get(key)

        if existing is None:
            by_key[key] = CrawlEndpoint(
                method=cap.method.upper(),
                path_template=templated_path,
                host=parts.netloc,
                scheme=parts.scheme or "https",
                query_params=query_params,
                path_params=path_params,
                example_request=cap,
                example_requests=[cap],
                status_codes_seen=[cap.status_code] if cap.status_code is not None else [],
                hit_count=1,
                discovery_source=source,
            )
            seen_variants[key] = {variant_key}
        else:
            existing.hit_count += 1
            existing.query_params = sorted(set(existing.query_params) | set(query_params))
            if cap.status_code is not None and cap.status_code not in existing.status_codes_seen:
                existing.status_codes_seen.append(cap.status_code)
            if source == "observed":
                existing.discovery_source = "observed"
            if variant_key not in seen_variants[key]:
                seen_variants[key].add(variant_key)
                existing.example_requests.append(cap)

    return sorted(by_key.values(), key=lambda e: (e.host, e.path_template, e.method))
