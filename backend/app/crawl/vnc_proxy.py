"""
Relays the browser viewer's noVNC traffic through the backend.

Each crawl session's noVNC web client runs inside its Docker container and is
published on a loopback-only host port (see VncBrowserContainer.start). The
browser never talks to that port directly: the viewer's iframe loads
/api/crawl/{session_id}/vnc/... from the same origin the app was served from,
and this module forwards those requests to 127.0.0.1:{novnc_port}. That keeps
the whole app reachable through a single public port.

Two kinds of traffic are relayed:
- plain HTTP: noVNC's HTML, JS and CSS assets (buffered; they are small);
- WebSocket: the RFB pixel/input stream, relayed frame-by-frame in both
  directions. noVNC requests the "binary" subprotocol, which is passed through.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from urllib.parse import quote

import httpx
from fastapi import Request, Response, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI, WebSocketException

# Path prefix under which a session's noVNC is exposed to the browser.
VNC_PREFIX = "/api/crawl/{session_id}/vnc"

# The relative URL the viewer iframe loads. `path` tells noVNC where its
# WebSocket lives: noVNC defaults to "websockify" relative to the host root,
# which would miss this prefix, so the full path is given explicitly.
VNC_PAGE = "vnc.html"
VNC_WS_PATH = "websockify"

# Headers that only describe a single hop and must not be relayed.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def novnc_page_url(session_id: str) -> str:
    """Same-origin URL the viewer iframe loads for a session."""
    ws_path = f"{VNC_PREFIX.format(session_id=session_id).lstrip('/')}/{VNC_WS_PATH}"
    query = f"autoconnect=true&resize=scale&path={quote(ws_path, safe='')}"
    return f"{VNC_PREFIX.format(session_id=session_id)}/{VNC_PAGE}?{query}"


def _upstream_base(port: int) -> str:
    return f"127.0.0.1:{port}"


async def forward_http(request: Request, port: int, path: str) -> Response:
    """Forwards one HTTP request to the session's noVNC web server and returns its response."""
    url = f"http://{_upstream_base(port)}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Ask for an uncompressed body so the buffered bytes can be returned as-is.
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "accept-encoding", "content-length"} | _HOP_BY_HOP
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            upstream = await client.request(request.method, url, headers=forwarded_headers)
        except httpx.HTTPError:
            return Response(content="noVNC is not reachable", status_code=502, media_type="text/plain")

    # httpx has already decoded any content-encoding, and Starlette sets the length itself.
    response_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in {"content-length", "content-encoding"} | _HOP_BY_HOP
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


async def relay_websocket(websocket: WebSocket, port: int, path: str) -> None:
    """Relays one WebSocket connection to the session's noVNC WebSocket endpoint."""
    requested = list(websocket.scope.get("subprotocols") or [])
    subprotocol = "binary" if "binary" in requested else None

    query = websocket.scope.get("query_string", b"").decode()
    url = f"ws://{_upstream_base(port)}/{path}" + (f"?{query}" if query else "")

    # Connect upstream before accepting the browser's socket, so a dead noVNC
    # is reported as a failed handshake instead of an open socket that closes.
    try:
        upstream = await ws_connect(
            url,
            subprotocols=[subprotocol] if subprotocol else None,
            max_size=None,  # RFB frames can be large; let the upstream decide.
        )
    except (OSError, InvalidHandshake, InvalidURI, WebSocketException):
        await websocket.close(code=1011)
        return

    await websocket.accept(subprotocol=subprotocol)

    async def browser_to_novnc() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
            elif message.get("text") is not None:
                await upstream.send(message["text"])

    async def novnc_to_browser() -> None:
        async for message in upstream:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)

    tasks = [asyncio.create_task(browser_to_novnc()), asyncio.create_task(novnc_to_browser())]
    try:
        # Either side closing ends the relay; the other direction is then cancelled.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, ConnectionClosed, WebSocketDisconnect, RuntimeError, OSError):
                await task
        with suppress(Exception):
            await upstream.close()
        with suppress(Exception):
            await websocket.close()
