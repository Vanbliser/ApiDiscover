from __future__ import annotations

import asyncio

import dns.asyncresolver
import dns.exception

from app.core.config import ProviderConfig
from app.core.models import SubdomainResult, SubdomainSource
from app.recon.wordlist import DEFAULT_SUBDOMAIN_WORDLIST


class DnsBruteForceProvider:
    """Active subdomain discovery via wordlist-based DNS resolution against the target."""

    name = "dns_bruteforce"
    requires_api_key = False

    def __init__(self, wordlist: list[str] | None = None, concurrency: int = 25) -> None:
        self.wordlist = wordlist or DEFAULT_SUBDOMAIN_WORDLIST
        self.concurrency = concurrency

    async def _resolve(self, hostname: str, resolver: "dns.asyncresolver.Resolver") -> bool:
        try:
            await resolver.resolve(hostname, "A")
            return True
        except (dns.exception.DNSException, OSError):
            return False

    async def query(self, domain: str, config: ProviderConfig | None) -> list[SubdomainResult]:
        if config is not None and not config.enabled:
            return []

        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = 3
        resolver.lifetime = 3

        sem = asyncio.Semaphore(self.concurrency)
        found: list[str] = []

        async def check(word: str) -> None:
            hostname = f"{word}.{domain}"
            async with sem:
                if await self._resolve(hostname, resolver):
                    found.append(hostname)

        await asyncio.gather(*(check(w) for w in self.wordlist))

        return [
            SubdomainResult(hostname=h, source=SubdomainSource.DNS_BRUTEFORCE, provider=self.name)
            for h in sorted(found)
        ]
