from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from app.core.config import provider_config_store
from app.core.models import LiveHost
from app.recon.active import DnsBruteForceProvider
from app.recon.base import ReconProvider
from app.recon.passive import CrtShProvider
from app.recon.third_party import THIRD_PARTY_PROVIDERS
from app.recon.wallarm import WallarmProvider


def default_providers() -> list[ReconProvider]:
    return [CrtShProvider(), DnsBruteForceProvider(), *THIRD_PARTY_PROVIDERS, WallarmProvider()]


async def _probe_one(hostname: str) -> LiveHost:
    for scheme in ("https", "http"):
        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, verify=False) as client:
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


class ProviderError:
    """A provider's query() raised — surfaced to the caller instead of being
    silently treated as zero results, so e.g. bad/expired Wallarm credentials
    show up as a visible error rather than a recon run that just ends with
    nothing and no explanation."""

    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        self.message = message


StreamItem = LiveHost | ProviderError


async def run_recon_streaming(
    domains: list[str], providers: list[ReconProvider] | None = None, probe_concurrency: int = 20
) -> AsyncIterator[StreamItem]:
    """
    Yields LiveHost items as soon as each one's liveness probe resolves, and
    ProviderError items as soon as a provider's query() raises — instead of
    waiting for every provider + every probe to finish first, and instead of
    silently swallowing provider failures as if they were zero results.

    `domains` may be empty — in that case only account-wide providers (those
    with `account_wide = True`, e.g. Wallarm) run, since domain-scoped
    providers have nothing to scope to. Domain-scoped providers run once per
    entered domain; account-wide providers run exactly once total regardless
    of how many domains were entered.
    """
    providers = providers or default_providers()
    sem = asyncio.Semaphore(probe_concurrency)
    seen_hosts: dict[str, LiveHost] = {}
    queue: asyncio.Queue[StreamItem | None] = asyncio.Queue()
    pending_probes: set[asyncio.Task] = set()

    async def probe_and_enqueue(hostname: str, provider_name: str) -> None:
        async with sem:
            existing = seen_hosts.get(hostname)
            if existing is not None:
                if provider_name not in existing.sources:
                    existing.sources.append(provider_name)
                    await queue.put(existing)
                return
            live_host = await _probe_one(hostname)
            live_host.sources = [provider_name]
            seen_hosts[hostname] = live_host
            await queue.put(live_host)

    async def run_provider(provider: ReconProvider, domain: str | None) -> None:
        config = provider_config_store.get(provider.name)
        try:
            results = await provider.query(domain, config)
        except Exception as e:
            await queue.put(ProviderError(provider.name, str(e)))
            return
        for r in results:
            task = asyncio.ensure_future(probe_and_enqueue(r.hostname, r.provider))
            pending_probes.add(task)
            task.add_done_callback(pending_probes.discard)

    domain_scoped = [p for p in providers if not p.account_wide]
    account_wide = [p for p in providers if p.account_wide]

    provider_tasks = [asyncio.ensure_future(run_provider(p, None)) for p in account_wide]
    for domain in domains:
        provider_tasks += [asyncio.ensure_future(run_provider(p, domain)) for p in domain_scoped]

    async def wait_and_close() -> None:
        await asyncio.gather(*provider_tasks)
        # Providers may still be spawning probe tasks up to the moment they
        # return, so re-check pending_probes until it's actually empty.
        while pending_probes:
            await asyncio.gather(*list(pending_probes))
        await queue.put(None)

    closer = asyncio.ensure_future(wait_and_close())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        closer.cancel()
