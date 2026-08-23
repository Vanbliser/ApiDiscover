from __future__ import annotations

import uuid
from urllib.parse import parse_qsl, urlsplit

from app.core.models import CapturedRequest, CrawlEndpoint


def _build_item(ep: CrawlEndpoint, cap: CapturedRequest, suffix_name_with_query: bool) -> dict:
    """
    One concrete Postman item for a single captured variant — real header
    values, real query values (not the deduplicated, value-blanked
    query_params list on CrawlEndpoint, which only tracks param *names*
    across every repeat and is used for OpenAPI's schema-oriented parameter
    list instead). `cap` is one entry from ep.example_requests.
    """
    url_path = ep.path_template.strip("/").split("/")
    headers = [{"key": k, "value": v} for k, v in cap.request_headers.items()]
    body = {"mode": "raw", "raw": cap.request_body} if cap.request_body else None

    query_pairs = parse_qsl(urlsplit(cap.url).query)
    query_string = "&".join(f"{k}={v}" for k, v in query_pairs)

    host_without_port = ep.host.split(":")[0]
    name = f"{ep.method} {ep.host}{ep.path_template}"
    if suffix_name_with_query and query_string:
        name += f"?{query_string}"

    return {
        "name": name,
        "request": {
            "method": ep.method,
            "header": headers,
            # Postman auto-detects a literal "Authorization: Bearer ..."
            # header on import and moves it into the request's Auth tab,
            # then regenerates that header from the Auth tab's own state at
            # send time — which is empty/inherited by default here, since
            # nothing above ever sets it, silently overriding the real
            # captured token and causing a 401 on replay. Explicit
            # "noauth" tells Postman not to manage or touch this request's
            # auth at all, so the captured header's exact value is sent
            # as-is, unchanged, exactly as it was recorded during the crawl.
            "auth": {"type": "noauth"},
            "body": body,
            "url": {
                "raw": f"{ep.scheme}://{ep.host}/{'/'.join(url_path)}"
                + (f"?{query_string}" if query_string else ""),
                "protocol": ep.scheme,
                "host": host_without_port.split("."),
                "port": ep.host.split(":")[1] if ":" in ep.host else None,
                "path": url_path,
                "query": [{"key": k, "value": v} for k, v in query_pairs],
            },
        },
        "response": [],
    }


def _build_items(ep: CrawlEndpoint) -> list[dict]:
    # Every distinct query-value combination captured for this endpoint
    # becomes its own item — one endpoint hit with different parameter
    # values (e.g. GET /search?q=foo and GET /search?q=bar) is multiple real
    # requests, not one request with the values thrown away. Only suffix
    # names with the query string when there's more than one variant, so
    # the common single-variant case keeps a clean, plain name.
    variants = ep.example_requests or ([ep.example_request] if ep.example_request else [])
    multiple = len(variants) > 1
    return [_build_item(ep, cap, suffix_name_with_query=multiple) for cap in variants]


def build_postman_collection(
    endpoints: list[CrawlEndpoint], name: str = "Discovered API", group_by_host: bool = False
) -> dict:
    if group_by_host:
        folders: dict[str, list[dict]] = {}
        for ep in endpoints:
            folders.setdefault(ep.host, []).extend(_build_items(ep))
        items = [
            {"name": host, "item": folders[host]}
            for host in sorted(folders)
        ]
    else:
        items = [item for ep in endpoints for item in _build_items(ep)]

    return {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }
