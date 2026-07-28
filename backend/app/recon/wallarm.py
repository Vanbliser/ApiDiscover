from __future__ import annotations

from app.core.config import ProviderConfig
from app.recon.base import PaginatedApiProvider


class WallarmProvider(PaginatedApiProvider):
    """
    Wallarm attack-surface subdomain listing.

    POST https://<host>/v1/attack_surface/subdomains
    body: {"client_id": ..., "offset": ..., "limit": ..., "token": ...}
    auth: wsess cookie + token in body.

    Configure via ProviderConfig:
      - api_key           -> used as the `token` body field
      - extra.client_id   -> Wallarm client_id
      - extra.api_host    -> optional override, defaults to us1.api.wallarm.com
      - cookies.wsess     -> wsess session cookie
    """

    name = "wallarm"
    page_size = 100

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        host = config.extra.get("api_host", "us1.api.wallarm.com")
        return f"https://{host}/v1/attack_surface/subdomains"

    def build_body(self, domain: str, config: ProviderConfig, offset: int, limit: int) -> dict:
        return {
            "client_id": int(config.extra.get("client_id", 0)),
            "offset": offset,
            "limit": limit,
            "token": config.api_key,
        }

    def parse_page(self, domain: str, payload: object) -> list[str]:
        """
        Wallarm's endpoint has no domain filter — it lists the whole account's
        attack surface — so filter to hosts under the requested domain here.
        """
        if not isinstance(payload, list):
            return []
        return [
            item["host"]
            for item in payload
            if isinstance(item, dict) and item.get("host") and item["host"].endswith(domain)
        ]
