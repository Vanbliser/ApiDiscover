from __future__ import annotations

import httpx

from app.core.config import ProviderConfig
from app.core.models import SubdomainResult, SubdomainSource


class CrtShProvider:
    """Passive OSINT via certificate transparency logs (crt.sh). No API key needed."""

    name = "crt_sh"
    requires_api_key = False
    account_wide = False

    async def query(self, domain: str, config: ProviderConfig | None) -> list[SubdomainResult]:
        if config is not None and not config.enabled:
            return []

        url = "https://crt.sh/"
        params = {"q": f"%.{domain}", "output": "json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            try:
                rows = resp.json()
            except ValueError:
                return []

        hostnames: set[str] = set()
        for row in rows:
            name_value = row.get("name_value", "")
            for candidate in name_value.split("\n"):
                candidate = candidate.strip().lstrip("*.")
                if candidate.endswith(domain):
                    hostnames.add(candidate)

        return [
            SubdomainResult(hostname=h, source=SubdomainSource.PASSIVE_CT, provider=self.name)
            for h in sorted(hostnames)
        ]
