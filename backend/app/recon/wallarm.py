from __future__ import annotations

from app.core.config import ProviderConfig
from app.recon.base import PaginatedApiProvider


class WallarmProvider(PaginatedApiProvider):
    """
    Wallarm attack-surface subdomain listing.

    POST https://<host>/v1/attack_surface/subdomains
    body: {"client_id": ..., "offset": ..., "limit": ..., "token": ...}
    auth: wsess cookie + token in body.

    This is account-wide, not domain-scoped — Wallarm's API has no domain
    filter, it always returns the full attack surface for the configured
    account. The orchestrator calls it once per recon run regardless of how
    many (or how few) domains were entered.

    Configure via ProviderConfig:
      - api_key           -> used as the `token` body field
      - extra.client_id   -> Wallarm client_id
      - extra.api_host    -> optional override, defaults to us1.api.wallarm.com
      - cookies.wsess     -> wsess session cookie
    """

    name = "wallarm"
    account_wide = True
    page_size = 100

    def build_url(self, domain: str | None, config: ProviderConfig) -> str:
        host = config.extra.get("api_host", "us1.api.wallarm.com").strip()
        # Accept either a bare host ("us1.api.wallarm.com") or a full base
        # URL/path someone pasted from Wallarm's docs (e.g. already including
        # "https://" and/or "/v1/attack_surface/subdomains") without doubling
        # the path when the endpoint suffix is already present.
        host = host.removeprefix("https://").removeprefix("http://")
        host = host.rstrip("/").removesuffix("/v1/attack_surface/subdomains")
        return f"https://{host}/v1/attack_surface/subdomains"

    def build_body(self, domain: str | None, config: ProviderConfig, offset: int, limit: int) -> dict:
        return {
            "client_id": int(config.extra.get("client_id", 0)),
            "offset": offset,
            "limit": limit,
            "token": config.api_key,
        }

    def parse_page(self, domain: str | None, payload: object) -> list[str]:
        if isinstance(payload, dict):
            # Wallarm returns HTTP 200 with the real outcome embedded in the
            # body on auth failure, e.g. {"status": 403, "body": "User not
            # authenticated"} — raise_for_status() never sees this, so it
            # must be detected here or it looks identical to "zero results".
            status = payload.get("status")
            if isinstance(status, int) and status >= 400:
                message = payload.get("body") or payload.get("message") or "unknown error"
                raise RuntimeError(f"Wallarm API error {status}: {message}")
            return []
        if not isinstance(payload, list):
            return []
        return [item["host"] for item in payload if isinstance(item, dict) and item.get("host")]
