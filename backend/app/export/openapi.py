from __future__ import annotations

from app.core.models import CrawlEndpoint


def build_openapi_spec(endpoints: list[CrawlEndpoint], title: str = "Discovered API") -> dict:
    host_schemes: dict[str, str] = {}
    for e in endpoints:
        host_schemes.setdefault(e.host, e.scheme)
    servers = [{"url": f"{scheme}://{host}"} for host, scheme in sorted(host_schemes.items())]

    single_host = len(host_schemes) <= 1

    # Multiple hosts can expose the same path+method (e.g. GET /health on both
    # api.a.com and api.b.com). OpenAPI only allows one operation per
    # (path, method), so true collisions need the host folded into the path;
    # everything else keeps its real, unprefixed path and gets disambiguated
    # with a per-operation `servers` override instead (spec-correct — avoids
    # baking the host into the path string, which breaks server+path
    # composition when re-imported elsewhere, e.g. Postman's {{baseUrl}}).
    seen_path_methods: dict[tuple[str, str], str] = {}
    colliding: set[tuple[str, str]] = set()
    for ep in endpoints:
        key = (ep.path_template, ep.method)
        prior_host = seen_path_methods.get(key)
        if prior_host is not None and prior_host != ep.host:
            colliding.add(key)
        else:
            seen_path_methods[key] = ep.host

    paths: dict[str, dict] = {}
    for ep in endpoints:
        key = (ep.path_template, ep.method)
        is_collision = not single_host and key in colliding
        path_key = f"/{ep.host}{ep.path_template}" if is_collision else ep.path_template
        needs_server_override = not single_host and not is_collision and len(host_schemes) > 1

        path_item = paths.setdefault(path_key, {})

        header_params = []
        if ep.example_request:
            header_params = [
                {
                    "name": h,
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "example": v},
                }
                for h, v in ep.example_request.request_headers.items()
            ]

        parameters = (
            [
                {
                    "name": p,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
                for p in ep.path_params
            ]
            + [
                {
                    "name": q,
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                }
                for q in ep.query_params
            ]
            + header_params
        )

        responses = {
            str(code): {"description": f"Observed response ({ep.hit_count} hit(s))"}
            for code in (ep.status_codes_seen or [200])
        }

        operation = {
            "summary": f"{ep.method} {ep.path_template}",
            "parameters": parameters,
            "responses": responses,
            "x-discovered-host": ep.host,
            "x-hit-count": ep.hit_count,
        }
        if needs_server_override:
            operation["servers"] = [{"url": f"{ep.scheme}://{ep.host}"}]

        path_item[ep.method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": "0.1.0"},
        "servers": servers,
        "paths": paths,
    }
