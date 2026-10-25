from __future__ import annotations

import asyncio
import socket
import threading
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Points saved-session storage and upload scratch space at a temp dir, and
    clears the in-memory active-session registry so tests can't leak into each other."""
    from app.core import sessions_store
    from app.crawl import session as crawl_session

    root = tmp_path / "sessions"
    monkeypatch.setattr(sessions_store, "SESSIONS_ROOT", root)
    monkeypatch.setattr(crawl_session, "UPLOADS_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(crawl_session, "_sessions", {})
    return root


@pytest.fixture
def free_port() -> int:
    """A loopback port with nothing listening on it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _select_subprotocol(connection, subprotocols):
    return "binary" if "binary" in subprotocols else None


@pytest.fixture
def fake_novnc():
    """
    Stands in for websockify inside the vnc-browser container: one loopback
    port that serves plain HTTP (a text page echoing the request path + query)
    and WebSocket echo on /websockify. Yields the port.
    """
    ready = threading.Event()
    stop = threading.Event()
    info: dict[str, int] = {}

    async def echo(ws):
        async for message in ws:
            await ws.send(message)

    def process_request(connection, request):
        if request.path.startswith("/websockify"):
            return None  # let the WebSocket upgrade through
        body = f"page:{request.path}".encode()
        return Response(200, "OK", Headers({"Content-Type": "text/plain", "Content-Length": str(len(body))}), body)

    async def main():
        async with serve(
            echo,
            "127.0.0.1",
            0,
            process_request=process_request,
            select_subprotocol=_select_subprotocol,
        ) as server:
            info["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.02)

    thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    thread.start()
    assert ready.wait(5), "fake noVNC server did not start"
    yield info["port"]
    stop.set()
    thread.join(5)


@pytest.fixture
def active_session(monkeypatch, fake_novnc):
    """Registers one fake active session (id "s1") whose noVNC is the fake server."""
    from app.api import routes_crawl

    session = SimpleNamespace(session_id="s1", container=SimpleNamespace(novnc_port=fake_novnc))
    monkeypatch.setattr(routes_crawl, "get_session", lambda sid: session if sid == "s1" else None)
    return session
