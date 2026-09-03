from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core import sessions_store
from app.crawl.container import check_proxy_reachable
from app.crawl.session import (
    STATIC_FILE_EXTENSION_GROUPS,
    create_resumed_session,
    create_session,
    get_session,
    is_session_active,
    remove_session,
)
from app.crawl.walker import DomWalker
from app.export.normalize import normalize_captures
from app.export.openapi import build_openapi_spec
from app.export.postman import build_postman_collection

router = APIRouter(prefix="/api/crawl", tags=["crawl"])

_walkers: dict[str, DomWalker] = {}

MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB
UPLOAD_CHUNK_BYTES = 1024 * 1024


class StartCrawlRequest(BaseModel):
    start_url: str
    # "host:port" of an intercepting proxy (e.g. Burp Suite) to route this
    # session's browser traffic through, decided here at launch since
    # Chrome's --proxy-server can't be changed on a running browser — see
    # VncBrowserContainer.proxy_server.
    proxy_server: str | None = None
    # When True, the browser profile and captured-request/exclusion history
    # survive this session being stopped, resumable later via
    # POST /sessions/{id}/resume — see CrawlSession.save_session.
    save_session: bool = False


class ResumeSessionRequest(BaseModel):
    # Optional override of the proxy this saved session originally used —
    # defaults to whatever was saved if omitted.
    proxy_server: str | None = None


class ExcludeHostRequest(BaseModel):
    host: str


class ExcludeEndpointRequest(BaseModel):
    method: str
    host: str
    path_template: str


class ExcludeExtensionRequest(BaseModel):
    extension: str


class ExcludeMethodRequest(BaseModel):
    method: str


class ProxyCheckRequest(BaseModel):
    host: str
    port: int


@router.get("/static-extension-groups")
def get_static_extension_groups():
    """
    The preset extension groups behind the "Exclude static files" quick
    toggle (css/html/js/images/fonts) — returned so the frontend's chip list
    stays in sync with the backend's actual filter instead of duplicating
    the list in two places.
    """
    return {group: sorted(exts) for group, exts in STATIC_FILE_EXTENSION_GROUPS.items()}


@router.post("/proxy/check")
async def check_proxy(req: ProxyCheckRequest):
    """
    Pure reachability probe, run *before* Launch browser — lets the user
    verify their proxy address from inside a container on this Docker
    network (see check_proxy_reachable for why it can't just be checked
    from the backend host directly) before committing to it, since
    --proxy-server is fixed for a session's whole lifetime once launched.
    """
    ok, message = await check_proxy_reachable(req.host, req.port)
    return {"reachable": ok, "message": message}


@router.post("/start")
async def start_crawl(req: StartCrawlRequest):
    session = create_session(proxy_server=req.proxy_server, save_session=req.save_session)
    await session.start(req.start_url)
    return {"session_id": session.session_id, "novnc_url": session.novnc_url}


@router.get("/sessions")
async def list_sessions():
    """
    Saved sessions available to resume, scanned from disk. `endpoint_count` is
    a raw captured-request count, not a deduplicated endpoint count — computing
    the real thing would mean normalizing every saved session's full history on
    every list call, which is wasted work for a view that's just a picker.
    `active` lets the frontend grey out "Resume" instead of letting it fail.
    """
    metas = sessions_store.list_saved_sessions()
    return {
        "sessions": [
            {
                "session_id": m.session_id,
                "label": m.label,
                "start_url": m.start_url,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
                "endpoint_count": sessions_store.count_captured(m.session_id),
                "active": is_session_active(m.session_id),
            }
            for m in metas
        ]
    }


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, req: ResumeSessionRequest | None = None):
    if is_session_active(session_id):
        raise HTTPException(status_code=409, detail="session is already active")
    meta = sessions_store.load_meta(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="saved session not found")

    proxy_server = (req.proxy_server if req else None) or meta.proxy_server
    session = create_resumed_session(session_id, proxy_server=proxy_server)
    try:
        await session.resume(meta.start_url)
    except Exception:
        remove_session(session_id)
        raise
    return {
        "session_id": session.session_id,
        "novnc_url": session.novnc_url,
        "captured_count": len(session.captured),
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if is_session_active(session_id):
        raise HTTPException(status_code=409, detail="cannot delete an active session; stop it first")
    sessions_store.delete_saved_session(session_id)
    return {"status": "deleted"}


@router.get("/{session_id}/endpoints")
async def view_endpoints(session_id: str):
    """Current normalized, exclusion-filtered endpoints — safe to poll anytime during a crawl."""
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}

    endpoints = normalize_captures(session.visible_captures())
    # example_requests (every distinct query-value variant, full headers +
    # body each) is only needed by the export step — excluded here since
    # this endpoint is polled repeatedly during a crawl and the frontend's
    # live view never renders per-variant detail, just the aggregate row.
    return {"endpoints": [e.model_dump(exclude={"example_requests"}) for e in endpoints]}


@router.get("/{session_id}/exclusions")
async def list_exclusions(session_id: str):
    """
    Currently-excluded hosts/endpoints for this session — the frontend needs
    this separately from /endpoints, since an excluded host's own endpoints
    (and thus any UI derived only from the visible endpoint list) disappear
    from that response entirely, but the excluded host itself still needs a
    place to show a "re-include" action.
    """
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    return {
        "hosts": sorted(session.excluded_hosts),
        "endpoints": [
            {"method": method, "host": host, "path_template": path_template}
            for method, host, path_template in sorted(session.excluded_endpoints)
        ],
        "extensions": sorted(session.excluded_extensions),
        "methods": sorted(session.excluded_methods),
    }


@router.post("/{session_id}/exclude-host")
async def exclude_host(session_id: str, req: ExcludeHostRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_host(req.host)
    return {"status": "ok"}


@router.post("/{session_id}/include-host")
async def include_host(session_id: str, req: ExcludeHostRequest):
    """
    Undoes exclude-host. Since exclusion is a view filter rather than
    deletion (see CrawlSession.visible_captures), this instantly restores
    everything captured for that host, including while it was excluded —
    not just resuming capture of new matching requests going forward.
    """
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.include_host(req.host)
    return {"status": "ok"}


@router.post("/{session_id}/exclude-endpoint")
async def exclude_endpoint(session_id: str, req: ExcludeEndpointRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_endpoint(req.method, req.host, req.path_template)
    return {"status": "ok"}


@router.post("/{session_id}/include-endpoint")
async def include_endpoint(session_id: str, req: ExcludeEndpointRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.include_endpoint(req.method, req.host, req.path_template)
    return {"status": "ok"}


@router.post("/{session_id}/exclude-extension")
async def exclude_extension(session_id: str, req: ExcludeExtensionRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_extension(req.extension)
    return {"status": "ok"}


@router.post("/{session_id}/include-extension")
async def include_extension(session_id: str, req: ExcludeExtensionRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.include_extension(req.extension)
    return {"status": "ok"}


@router.post("/{session_id}/exclude-method")
async def exclude_method(session_id: str, req: ExcludeMethodRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_method(req.method)
    return {"status": "ok"}


@router.post("/{session_id}/include-method")
async def include_method(session_id: str, req: ExcludeMethodRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.include_method(req.method)
    return {"status": "ok"}


@router.post("/{session_id}/scan-js")
async def scan_js(session_id: str):
    """
    On-demand: fetch JS bundles referenced by the current page (and chunks
    they reference), extract candidate endpoint paths, and verify each with
    a real request. Can take a while depending on how many scripts/candidates
    are found — prefer the WebSocket "scan_js" control message if you want
    a completion event instead of waiting on this request.
    """
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    found = await session.run_js_scan()
    return {"found_count": len(found)}


@router.post("/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile):
    """
    Saves an uploaded file into this session's uploads directory, which is
    bind-mounted into the running container at /root/Uploads — so it shows
    up for the user to pick from the native file-picker triggered by the
    target site's own <input type=file>. Capped at 1GB, streamed to disk
    rather than buffered fully in memory.
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    filename = os.path.basename(file.filename or "upload")
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")

    dest = session.uploads_dir / filename
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="file exceeds 1GB limit")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"upload failed: {e}")

    return {"status": "ok", "filename": filename, "size": written}


@router.get("/{session_id}/export")
async def export_results(session_id: str, group_by_host: bool = False):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}

    endpoints = normalize_captures(session.visible_captures())
    return {
        "openapi": build_openapi_spec(endpoints),
        "postman": build_postman_collection(endpoints, group_by_host=group_by_host),
        "endpoint_count": len(endpoints),
    }


@router.post("/{session_id}/stop")
async def stop_crawl(session_id: str):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    walker = _walkers.pop(session_id, None)
    if walker:
        walker.stop()
    await session.stop()
    remove_session(session_id)
    return {"status": "stopped"}


@router.websocket("/{session_id}/stream")
async def crawl_stream(websocket: WebSocket, session_id: str):
    """
    Relays crawler status + captured-request events to the frontend, and
    receives autonomous-crawl control messages. The browser's picture/input
    goes over noVNC directly (embedded via `novnc_url`) — this socket is not
    in that path at all.
    """
    await websocket.accept()
    session = get_session(session_id)
    if session is None:
        await websocket.send_json({"type": "error", "message": "session not found"})
        await websocket.close()
        return

    loop = asyncio.get_event_loop()

    def on_capture(capture) -> None:
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "capture", "data": capture.model_dump()}),
            loop,
        )

    session.set_capture_handler(on_capture)

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle_control_message(session, session_id, msg, websocket)
    except WebSocketDisconnect:
        pass


async def _handle_control_message(session, session_id: str, msg: dict, websocket: WebSocket) -> None:
    msg_type = msg.get("type")

    if msg_type == "start_autonomous":
        if session_id in _walkers:
            return

        def on_status_change(status) -> None:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "status", "status": status.value}), asyncio.get_event_loop()
            )

        walker = DomWalker(session.page, on_status_change=on_status_change)
        _walkers[session_id] = walker
        asyncio.create_task(walker.run())
    elif msg_type == "resume_autonomous":
        walker = _walkers.get(session_id)
        if walker:
            walker.resume()
    elif msg_type == "stop_autonomous":
        walker = _walkers.pop(session_id, None)
        if walker:
            walker.stop()
    elif msg_type == "scan_js":
        async def do_scan() -> None:
            try:
                found = await session.run_js_scan()
                await websocket.send_json({"type": "js_scan_done", "found_count": len(found)})
            except Exception as e:
                await websocket.send_json({"type": "js_scan_error", "message": str(e)})

        asyncio.create_task(do_scan())
