from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.config import ProviderConfig, provider_config_store
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
