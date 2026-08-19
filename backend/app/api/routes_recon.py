from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.config import (
    ProviderConfig,
    clear_proxy_ca_cert,
    get_proxy_ca_cert_path,
    provider_config_store,
    set_proxy_ca_cert,
)
from app.recon.orchestrator import ProviderError, run_recon_streaming

router = APIRouter(prefix="/api/recon", tags=["recon"])


class ProviderConfigRequest(BaseModel):
    name: str
    enabled: bool = True
    api_key: str | None = None
    cookies: dict[str, str] = {}
    extra: dict[str, str] = {}


@router.get("/providers")
def list_providers():
    """
    Returns real saved values (api_key, cookies) — this is a trusted,
    local-only tool, so the Settings page can show and let you verify what
    was actually saved rather than a masked placeholder. Still encrypted at
    rest (see ProviderConfigStore); this only affects what the API returns.
    """
    return [c.model_dump() for c in provider_config_store.list()]


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


@router.get("/proxy-ca-cert")
def get_proxy_ca_cert_status():
    """
    Whether an intercepting-proxy CA cert (e.g. Burp Suite's) is currently
    configured — used by the App Crawl panel to know whether HTTPS traffic
    routed through a proxy will actually validate cleanly for a *new*
    session, versus needing to be uploaded first. Applies at container
    start (see session.py) — uploading one now doesn't retroactively
    affect already-running sessions.
    """
    return {"configured": get_proxy_ca_cert_path() is not None}


@router.put("/proxy-ca-cert")
async def upload_proxy_ca_cert(file: UploadFile):
    body = await file.read()
    if not body.strip().startswith(b"-----BEGIN CERTIFICATE-----"):
        raise HTTPException(status_code=400, detail="not a PEM certificate (expected a -----BEGIN CERTIFICATE----- block)")
    set_proxy_ca_cert(body)
    return {"status": "ok"}


@router.delete("/proxy-ca-cert")
def delete_proxy_ca_cert():
    clear_proxy_ca_cert()
    return {"status": "ok"}


@router.websocket("/stream")
async def recon_stream(websocket: WebSocket):
    """
    Client sends {"domains": ["a.com", "b.com", ...]} to start a run; hosts
    stream back one at a time as they're discovered and liveness-probed,
    instead of waiting for every provider (and every probe) to finish first.

    `domains` may be an empty list — account-wide providers (e.g. Wallarm,
    which has no domain filter) still run in that case; domain-scoped
    providers are simply skipped since they'd have nothing to scope to.
    """
    await websocket.accept()
    try:
        msg = await websocket.receive_json()
        domains = [d.strip() for d in msg.get("domains", []) if d.strip()]

        async for item in run_recon_streaming(domains):
            if isinstance(item, ProviderError):
                await websocket.send_json(
                    {"type": "provider_error", "provider": item.provider_name, "message": item.message}
                )
            else:
                await websocket.send_json({"type": "host", "data": item.model_dump()})

        await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
