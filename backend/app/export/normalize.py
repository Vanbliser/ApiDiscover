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
    """
    by_key: dict[tuple[str, str, str], CrawlEndpoint] = {}

    for cap in captures:
        if cap.resource_type not in ("xhr", "fetch"):
            continue

        parts = urlsplit(cap.url)
        templated_path, path_params = templatize_path(parts.path)
        query_params = sorted({k for k, _ in parse_qsl(parts.query)})

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
                status_codes_seen=[cap.status_code] if cap.status_code is not None else [],
                hit_count=1,
            )
        else:
            existing.hit_count += 1
            existing.query_params = sorted(set(existing.query_params) | set(query_params))
            if cap.status_code is not None and cap.status_code not in existing.status_codes_seen:
                existing.status_codes_seen.append(cap.status_code)

    return sorted(by_key.values(), key=lambda e: (e.host, e.path_template, e.method))
