"""noVNC relay: the viewer's HTML/asset requests and its WebSocket, through /api/crawl/{id}/vnc/*."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.crawl.vnc_proxy import novnc_page_url
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# --- URL the viewer iframe loads ---------------------------------------------

def test_novnc_page_url_is_same_origin_relative():
    url = novnc_page_url("abc")
    assert url.startswith("/api/crawl/abc/vnc/vnc.html?")
    assert "://" not in url


def test_novnc_page_url_tells_noVNC_where_its_websocket_is():
    query = parse_qs(urlsplit(novnc_page_url("abc")).query)
    assert query["autoconnect"] == ["true"]
    assert query["resize"] == ["scale"]
    # noVNC would otherwise default to "websockify" at the host root.
    assert query["path"] == ["api/crawl/abc/vnc/websockify"]


# --- HTTP: noVNC's HTML and assets --------------------------------------------

def test_http_page_is_relayed_from_upstream(client, active_session):
    resp = client.get("/api/crawl/s1/vnc/vnc.html")
    assert resp.status_code == 200
    assert resp.text == "page:/vnc.html"


def test_http_query_string_is_forwarded(client, active_session):
    resp = client.get("/api/crawl/s1/vnc/vnc.html?autoconnect=true&resize=scale")
    assert resp.text == "page:/vnc.html?autoconnect=true&resize=scale"


def test_http_nested_asset_path_is_forwarded(client, active_session):
    resp = client.get("/api/crawl/s1/vnc/app/ui.js")
    assert resp.text == "page:/app/ui.js"


def test_http_unknown_session_is_404(client, active_session):
    resp = client.get("/api/crawl/nope/vnc/vnc.html")
    assert resp.status_code == 404


def test_http_upstream_down_is_502(client, monkeypatch, free_port):
    from app.api import routes_crawl

    session = type("S", (), {"container": type("C", (), {"novnc_port": free_port})()})()
    monkeypatch.setattr(routes_crawl, "get_session", lambda sid: session)
    resp = client.get("/api/crawl/s1/vnc/vnc.html")
    assert resp.status_code == 502


def test_hop_by_hop_headers_are_not_relayed(client, active_session):
    resp = client.get("/api/crawl/s1/vnc/vnc.html", headers={"Connection": "keep-alive"})
    assert "transfer-encoding" not in resp.headers
    assert resp.status_code == 200


# --- WebSocket: the RFB stream ------------------------------------------------

def test_websocket_binary_frames_round_trip(client, active_session):
    with client.websocket_connect("/api/crawl/s1/vnc/websockify", subprotocols=["binary"]) as ws:
        ws.send_bytes(b"\x03\x00\x01\x02")
        assert ws.receive_bytes() == b"\x03\x00\x01\x02"


def test_websocket_text_frames_round_trip(client, active_session):
    with client.websocket_connect("/api/crawl/s1/vnc/websockify") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "hello"


def test_websocket_many_frames_keep_order(client, active_session):
    with client.websocket_connect("/api/crawl/s1/vnc/websockify", subprotocols=["binary"]) as ws:
        for i in range(50):
            ws.send_bytes(bytes([i]))
        assert [ws.receive_bytes()[0] for _ in range(50)] == list(range(50))


def test_websocket_unknown_session_is_refused(client, active_session):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/crawl/nope/vnc/websockify"):
            pass


def test_websocket_upstream_down_is_refused(client, monkeypatch, free_port):
    from app.api import routes_crawl

    session = type("S", (), {"container": type("C", (), {"novnc_port": free_port})()})()
    monkeypatch.setattr(routes_crawl, "get_session", lambda sid: session)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/crawl/s1/vnc/websockify", subprotocols=["binary"]):
            pass
