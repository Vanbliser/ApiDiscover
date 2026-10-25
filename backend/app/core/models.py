from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CapturedRequest(BaseModel):
    method: str
    url: str
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: str | None = None
    status_code: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body_sample: str | None = None
    resource_type: str | None = None


class CrawlEndpoint(BaseModel):
    """Deduplicated/normalized endpoint derived from one or more CapturedRequests."""

    method: str
    path_template: str
    host: str
    scheme: str
    query_params: list[str] = Field(default_factory=list)
    path_params: list[str] = Field(default_factory=list)
    example_request: CapturedRequest | None = None
    # Every distinct request captured for this endpoint, deduplicated by
    # actual query-parameter *values* (not just names) — unlike
    # example_request (always just the first one seen), this preserves
    # every different value combination hit during the crawl, e.g.
    # GET /search?q=foo and GET /search?q=bar both survive here even though
    # they collapse into one endpoint entry for query_params/OpenAPI's
    # schema-oriented parameter list. Used by the Postman exporter, which is
    # concrete-request-oriented and needs one item per real variant rather
    # than one parameter schema per endpoint.
    example_requests: list[CapturedRequest] = Field(default_factory=list)
    status_codes_seen: list[int] = Field(default_factory=list)
    hit_count: int = 1
    # "observed": seen during real click-through traffic.
    # "js_scan_verified": found as a string literal in JS source, then
    # confirmed live via an actual verification request (see js_scan.py) —
    # never organically triggered by the crawler, so surfaced distinctly.
    discovery_source: str = "observed"


class CrawlerStatus(str, Enum):
    IDLE = "idle"
    MANUAL_CONTROL = "manual_control"
    AUTONOMOUS = "autonomous"
    STUCK_AWAITING_INPUT = "stuck_awaiting_input"
    FINISHED = "finished"
    ERROR = "error"
