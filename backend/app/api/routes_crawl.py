from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.crawl.session import create_session, get_session, remove_session
from app.crawl.walker import DomWalker
from app.export.normalize import normalize_captures
from app.export.openapi import build_openapi_spec
from app.export.postman import build_postman_collection

router = APIRouter(prefix="/api/crawl", tags=["crawl"])

_walkers: dict[str, DomWalker] = {}


class StartCrawlRequest(BaseModel):
    start_url: str


class ExcludeHostRequest(BaseModel):
    host: str


class ExcludeEndpointRequest(BaseModel):
    method: str
    host: str
    path_template: str


@router.post("/start")
async def start_crawl(req: StartCrawlRequest):
    session = create_session()
    await session.start(req.start_url)
    return {"session_id": session.session_id, "novnc_url": session.novnc_url}


@router.get("/{session_id}/endpoints")
async def view_endpoints(session_id: str):
    """Current normalized, exclusion-filtered endpoints — safe to poll anytime during a crawl."""
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}

    endpoints = normalize_captures(session.captured)
    return {"endpoints": [e.model_dump() for e in endpoints]}


@router.post("/{session_id}/exclude-host")
async def exclude_host(session_id: str, req: ExcludeHostRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_host(req.host)
    return {"status": "ok"}


@router.post("/{session_id}/exclude-endpoint")
async def exclude_endpoint(session_id: str, req: ExcludeEndpointRequest):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}
    session.exclude_endpoint(req.method, req.host, req.path_template)
    return {"status": "ok"}


@router.get("/{session_id}/export")
async def export_results(session_id: str, group_by_host: bool = False):
    session = get_session(session_id)
    if session is None:
        return {"error": "session not found"}

    endpoints = normalize_captures(session.captured)
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
