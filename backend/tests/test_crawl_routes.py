"""HTTP routes for App Crawl: start, saved sessions (list/resume/delete), and the viewer URL."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.api import routes_crawl
from app.core import sessions_store
from app.core.models import CapturedRequest
from app.crawl import session as crawl_session
from app.crawl.vnc_proxy import novnc_page_url
from app.main import app


@pytest.fixture
def client(isolated_storage):
    return TestClient(app)


class FakeSession:
    """Stands in for CrawlSession so no Docker container or browser is launched."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.started_with: str | None = None
        self.captured: list = []

    @property
    def novnc_url(self) -> str:
        return novnc_page_url(self.session_id)

    async def start(self, start_url: str) -> None:
        self.started_with = start_url

    async def resume(self, start_url: str) -> None:
        self.started_with = start_url


@pytest.fixture
def fake_launch(monkeypatch):
    created: list[FakeSession] = []

    def make(session_id="new-session", **_):
        s = FakeSession(session_id)
        created.append(s)
        crawl_session._sessions[session_id] = s
        return s

    monkeypatch.setattr(routes_crawl, "create_session", make)
    monkeypatch.setattr(routes_crawl, "create_resumed_session", lambda sid, proxy_server=None: make(sid))
    return created


# --- start / viewer URL -------------------------------------------------------

def test_start_returns_relative_viewer_url(client, fake_launch):
    resp = client.post("/api/crawl/start", json={"start_url": "https://example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "new-session"
    assert body["novnc_url"].startswith("/api/crawl/new-session/vnc/vnc.html?")
    assert "://" not in body["novnc_url"]
    assert fake_launch[0].started_with == "https://example.com"


def test_viewer_url_points_noVNC_at_the_proxied_websocket(client, fake_launch):
    body = client.post("/api/crawl/start", json={"start_url": "https://example.com"}).json()
    query = parse_qs(urlsplit(body["novnc_url"]).query)
    assert query["path"] == ["api/crawl/new-session/vnc/websockify"]


def test_start_passes_save_session_flag(client, monkeypatch):
    seen = {}

    def fake_create(proxy_server=None, save_session=False):
        seen["save_session"] = save_session
        return FakeSession("x")

    monkeypatch.setattr(routes_crawl, "create_session", fake_create)
    client.post("/api/crawl/start", json={"start_url": "https://example.com", "save_session": True})
    assert seen["save_session"] is True


# --- saved sessions -----------------------------------------------------------

def _save(session_id: str, start_url: str = "https://example.com") -> None:
    sessions_store.init_saved_session(session_id, start_url, None)


def test_list_sessions_empty(client):
    assert client.get("/api/crawl/sessions").json() == {"sessions": []}


def test_list_sessions_shows_saved_sessions_with_counts(client):
    _save("a")
    sessions_store.append_captured(
        "a",
        CapturedRequest(method="GET", url="https://example.com/api/x", status_code=200),
    )
    body = client.get("/api/crawl/sessions").json()
    assert len(body["sessions"]) == 1
    entry = body["sessions"][0]
    assert entry["session_id"] == "a"
    assert entry["endpoint_count"] == 1
    assert entry["active"] is False


def test_resume_unknown_session_is_404(client, fake_launch):
    assert client.post("/api/crawl/sessions/missing/resume", json={}).status_code == 404


def test_resume_restores_captured_count(client, fake_launch, monkeypatch):
    _save("a")
    sessions_store.append_captured(
        "a",
        CapturedRequest(method="GET", url="https://example.com/x", status_code=200),
    )
    body = client.post("/api/crawl/sessions/a/resume", json={}).json()
    assert body["session_id"] == "a"
    assert body["novnc_url"].startswith("/api/crawl/a/vnc/vnc.html?")


def test_resume_active_session_is_409(client, fake_launch):
    _save("a")
    crawl_session._sessions["a"] = FakeSession("a")
    assert client.post("/api/crawl/sessions/a/resume", json={}).status_code == 409


def test_delete_saved_session(client):
    _save("a")
    assert client.delete("/api/crawl/sessions/a").status_code == 200
    assert sessions_store.load_meta("a") is None


def test_delete_active_session_is_409(client, fake_launch):
    _save("a")
    crawl_session._sessions["a"] = FakeSession("a")
    assert client.delete("/api/crawl/sessions/a").status_code == 409
    assert sessions_store.load_meta("a") is not None


def test_active_flag_reflects_running_sessions(client, fake_launch):
    _save("a")
    crawl_session._sessions["a"] = FakeSession("a")
    entry = client.get("/api/crawl/sessions").json()["sessions"][0]
    assert entry["active"] is True


# --- static helpers -----------------------------------------------------------

def test_static_extension_groups_endpoint(client):
    body = client.get("/api/crawl/static-extension-groups").json()
    assert isinstance(body, dict) and body
