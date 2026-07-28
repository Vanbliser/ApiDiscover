from __future__ import annotations

import asyncio

import httpx

from app.core.config import provider_config_store
from app.core.models import LiveHost, SubdomainResult
from app.recon.active import DnsBruteForceProvider
from app.recon.base import ReconProvider
from app.recon.passive import CrtShProvider
from app.recon.third_party import THIRD_PARTY_PROVIDERS
from app.recon.wallarm import WallarmProvider


def default_providers() -> list[ReconProvider]:
    return [CrtShProvider(), DnsBruteForceProvider(), *THIRD_PARTY_PROVIDERS, WallarmProvider()]


async def run_recon(domain: str, providers: list[ReconProvider] | None = None) -> list[SubdomainResult]:
    providers = providers or default_providers()

    async def run_one(provider: ReconProvider) -> list[SubdomainResult]:
        config = provider_config_store.get(provider.name)
        try:
            return await provider.query(domain, config)
        except Exception:
            return []

    results = await asyncio.gather(*(run_one(p) for p in providers))

    merged: dict[str, LiveHost] = {}
    for provider_results in results:
        for r in provider_results:
            host = merged.setdefault(r.hostname, LiveHost(hostname=r.hostname, sources=[]))
            if r.provider not in host.sources:
                host.sources.append(r.provider)

    return [r for provider_results in results for r in provider_results]


async def probe_liveness(hostnames: list[str], concurrency: int = 20) -> list[LiveHost]:
    sem = asyncio.Semaphore(concurrency)

    async def probe(hostname: str) -> LiveHost:
        async with sem:
            for scheme in ("https", "http"):
                try:
                    async with httpx.AsyncClient(
                        timeout=6.0, follow_redirects=True, verify=False
                    ) as client:
                        resp = await client.get(f"{scheme}://{hostname}")
                        title = None
                        if "text/html" in resp.headers.get("content-type", ""):
                            start = resp.text.find("<title>")
                            end = resp.text.find("</title>")
                            if start != -1 and end != -1:
                                title = resp.text[start + 7 : end].strip()[:200]
                        return LiveHost(
                            hostname=hostname,
                            sources=[],
                            status_code=resp.status_code,
                            title=title,
                            server_header=resp.headers.get("server"),
                            reachable=True,
                        )
                except (httpx.HTTPError, OSError):
                    continue
            return LiveHost(hostname=hostname, sources=[], reachable=False)

    return await asyncio.gather(*(probe(h) for h in hostnames))


def merge_results(
    subdomain_results: list[SubdomainResult], live_hosts: list[LiveHost]
) -> list[LiveHost]:
    by_host: dict[str, LiveHost] = {h.hostname: h for h in live_hosts}
    for r in subdomain_results:
        host = by_host.get(r.hostname)
        if host is None:
            continue
        if r.provider not in host.sources:
            host.sources.append(r.provider)
    return list(by_host.values())
