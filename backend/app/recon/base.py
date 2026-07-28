from __future__ import annotations

from typing import Protocol

from app.core.config import ProviderConfig
from app.core.models import SubdomainResult


class ReconProvider(Protocol):
    """A source of subdomain/host data for a given root domain."""

    name: str
    requires_api_key: bool

    async def query(self, domain: str, config: ProviderConfig | None) -> list[SubdomainResult]: ...


class ApiListProvider:
    """
    Generic base for third-party recon APIs that return a list of hosts from a
    single authenticated GET request (Shodan, Censys, SecurityTrails, VirusTotal, ...).

    Subclasses only need to describe the request shape and how to pull hostnames
    out of the response — auth placement, concurrency, and error handling are shared.
    """

    name: str = "api_list_provider"
    requires_api_key: bool = True

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        raise NotImplementedError

    def build_headers(self, config: ProviderConfig) -> dict[str, str]:
        return {}

    def build_params(self, domain: str, config: ProviderConfig) -> dict[str, str]:
        return {}

    def parse_hostnames(self, domain: str, payload: object) -> list[str]:
        raise NotImplementedError

    async def query(self, domain: str, config: ProviderConfig | None):
        import httpx

        from app.core.models import SubdomainResult, SubdomainSource

        if config is None or not config.enabled:
            return []
        if self.requires_api_key and not config.api_key:
            return []

        url = self.build_url(domain, config)
        headers = self.build_headers(config)
        params = self.build_params(domain, config)

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()

        hostnames = self.parse_hostnames(domain, payload)
        return [
            SubdomainResult(hostname=h, source=SubdomainSource.THIRD_PARTY_API, provider=self.name)
            for h in dict.fromkeys(hostnames)
        ]


class PaginatedApiProvider:
    """
    Generic base for third-party recon APIs that require a POST body, cookie auth,
    and offset/limit-based pagination to retrieve the full result set (Wallarm, and
    any future provider with the same shape).

    Subclasses describe the request shape and how to parse one page's response;
    pagination (looping until a short/empty page comes back) is handled here.
    """

    name: str = "paginated_api_provider"
    requires_api_key: bool = True
    page_size: int = 100
    max_pages: int = 200

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        raise NotImplementedError

    def build_headers(self, config: ProviderConfig) -> dict[str, str]:
        return {}

    def build_cookies(self, config: ProviderConfig) -> dict[str, str]:
        return dict(config.cookies)

    def build_body(self, domain: str, config: ProviderConfig, offset: int, limit: int) -> dict:
        raise NotImplementedError

    def parse_page(self, domain: str, payload: object) -> list[str]:
        """Return hostnames found on this page (after any subclass-side filtering)."""
        raise NotImplementedError

    def page_item_count(self, payload: object) -> int:
        """
        Raw item count on this page, BEFORE any domain filtering `parse_page` applies.
        Used to detect the last page — a filtered result can look short even when
        the raw page was full, so pagination must not rely on parse_page's length.
        """
        return len(payload) if isinstance(payload, list) else 0

    async def query(self, domain: str, config: ProviderConfig | None) -> list[SubdomainResult]:
        import httpx

        from app.core.models import SubdomainResult, SubdomainSource

        if config is None or not config.enabled:
            return []
        if self.requires_api_key and not config.api_key:
            return []

        url = self.build_url(domain, config)
        headers = self.build_headers(config)
        cookies = self.build_cookies(config)

        all_hostnames: list[str] = []
        offset = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(self.max_pages):
                body = self.build_body(domain, config, offset, self.page_size)
                resp = await client.post(url, headers=headers, cookies=cookies, json=body)
                resp.raise_for_status()
                payload = resp.json()

                page_hostnames = self.parse_page(domain, payload)
                all_hostnames.extend(page_hostnames)

                if self.page_item_count(payload) < self.page_size:
                    break
                offset += self.page_size

        return [
            SubdomainResult(hostname=h, source=SubdomainSource.THIRD_PARTY_API, provider=self.name)
            for h in dict.fromkeys(all_hostnames)
        ]
