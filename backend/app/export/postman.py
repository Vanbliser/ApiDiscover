from __future__ import annotations

import uuid

from app.core.models import CrawlEndpoint


def _build_item(ep: CrawlEndpoint) -> dict:
    url_path = ep.path_template.strip("/").split("/")
    headers = []
    body = None
    if ep.example_request:
        headers = [
            {"key": k, "value": v}
            for k, v in ep.example_request.request_headers.items()
            if k.lower() not in ("cookie", "host")
        ]
        if ep.example_request.request_body:
            body = {"mode": "raw", "raw": ep.example_request.request_body}

    host_without_port = ep.host.split(":")[0]

    return {
        "name": f"{ep.method} {ep.host}{ep.path_template}",
        "request": {
            "method": ep.method,
            "header": headers,
            "body": body,
            "url": {
                "raw": f"{ep.scheme}://{ep.host}/{'/'.join(url_path)}",
                "protocol": ep.scheme,
                "host": host_without_port.split("."),
                "port": ep.host.split(":")[1] if ":" in ep.host else None,
                "path": url_path,
                "query": [{"key": q, "value": ""} for q in ep.query_params],
            },
        },
        "response": [],
    }


def build_postman_collection(
    endpoints: list[CrawlEndpoint], name: str = "Discovered API", group_by_host: bool = False
) -> dict:
    if group_by_host:
        folders: dict[str, list[dict]] = {}
        for ep in endpoints:
            folders.setdefault(ep.host, []).append(_build_item(ep))
        items = [
            {"name": host, "item": folders[host]}
            for host in sorted(folders)
        ]
    else:
        items = [_build_item(ep) for ep in endpoints]

    return {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }
