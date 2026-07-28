from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import ProviderConfig, provider_config_store
from app.recon.orchestrator import merge_results, probe_liveness, run_recon

router = APIRouter(prefix="/api/recon", tags=["recon"])


class RunReconRequest(BaseModel):
    domain: str
    probe_liveness: bool = True


class ProviderConfigRequest(BaseModel):
    name: str
    enabled: bool = True
    api_key: str | None = None
    cookies: dict[str, str] = {}
    extra: dict[str, str] = {}


@router.get("/providers")
def list_providers():
    return [c.model_dump(exclude={"api_key", "cookies"}) for c in provider_config_store.list()]


@router.put("/providers")
def upsert_provider(req: ProviderConfigRequest):
    config = ProviderConfig(
        name=req.name,
        enabled=req.enabled,
        api_key=req.api_key,
        cookies=req.cookies,
        extra=req.extra,
    )
    provider_config_store.set(config)
    return {"status": "ok"}


@router.post("/run")
async def run(req: RunReconRequest):
    subdomain_results = await run_recon(req.domain)
    hostnames = sorted({r.hostname for r in subdomain_results})

    live_hosts = []
    if req.probe_liveness and hostnames:
        live_hosts = await probe_liveness(hostnames)
        live_hosts = merge_results(subdomain_results, live_hosts)
    else:
        from app.core.models import LiveHost

        by_host: dict[str, LiveHost] = {}
        for r in subdomain_results:
            h = by_host.setdefault(r.hostname, LiveHost(hostname=r.hostname, sources=[]))
            if r.provider not in h.sources:
                h.sources.append(r.provider)
        live_hosts = list(by_host.values())

    return {"domain": req.domain, "hosts": [h.model_dump() for h in live_hosts]}
