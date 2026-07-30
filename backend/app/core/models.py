from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SubdomainSource(str, Enum):
    PASSIVE_CT = "passive_ct"
    DNS_BRUTEFORCE = "dns_bruteforce"
    THIRD_PARTY_API = "third_party_api"


class SubdomainResult(BaseModel):
    hostname: str
    source: SubdomainSource
    provider: str


class LiveHost(BaseModel):
    hostname: str
    sources: list[str]
    status_code: int | None = None
    title: str | None = None
    server_header: str | None = None
    resolved_ips: list[str] = Field(default_factory=list)
    reachable: bool = False


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


class RunMode(str, Enum):
    DOMAIN_RECON = "domain_recon"
    APP_CRAWL = "app_crawl"
    BOTH = "both"
