from __future__ import annotations

from app.core.config import ProviderConfig
from app.recon.base import ApiListProvider


class ShodanProvider(ApiListProvider):
    name = "shodan"

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        return f"https://api.shodan.io/dns/domain/{domain}"

    def build_params(self, domain: str, config: ProviderConfig) -> dict[str, str]:
        return {"key": config.api_key or ""}

    def parse_hostnames(self, domain: str, payload: object) -> list[str]:
        subdomains = payload.get("subdomains", []) if isinstance(payload, dict) else []
        return [f"{s}.{domain}" if s else domain for s in subdomains]


class CensysProvider(ApiListProvider):
    name = "censys"

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        return "https://search.censys.io/api/v2/hosts/search"

    def build_headers(self, config: ProviderConfig) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.api_key or ''}"}

    def build_params(self, domain: str, config: ProviderConfig) -> dict[str, str]:
        return {"q": domain}

    def parse_hostnames(self, domain: str, payload: object) -> list[str]:
        hits = payload.get("result", {}).get("hits", []) if isinstance(payload, dict) else []
        hostnames: list[str] = []
        for hit in hits:
            for name in hit.get("dns", {}).get("names", []) or []:
                if name.endswith(domain):
                    hostnames.append(name)
        return hostnames


class SecurityTrailsProvider(ApiListProvider):
    name = "securitytrails"

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        return f"https://api.securitytrails.com/v1/domain/{domain}/subdomains"

    def build_headers(self, config: ProviderConfig) -> dict[str, str]:
        return {"APIKEY": config.api_key or ""}

    def parse_hostnames(self, domain: str, payload: object) -> list[str]:
        subdomains = payload.get("subdomains", []) if isinstance(payload, dict) else []
        return [f"{s}.{domain}" for s in subdomains]


class VirusTotalProvider(ApiListProvider):
    name = "virustotal"

    def build_url(self, domain: str, config: ProviderConfig) -> str:
        return f"https://www.virustotal.com/api/v3/domains/{domain}/subdomains"

    def build_headers(self, config: ProviderConfig) -> dict[str, str]:
        return {"x-apikey": config.api_key or ""}

    def parse_hostnames(self, domain: str, payload: object) -> list[str]:
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [item.get("id", "") for item in data if item.get("id")]


THIRD_PARTY_PROVIDERS = [
    ShodanProvider(),
    CensysProvider(),
    SecurityTrailsProvider(),
    VirusTotalProvider(),
]
