"""App shell: health, CORS on the frontend origin, and serving the built UI from the backend."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend_static import mount_frontend
from app.main import app as real_app


@pytest.fixture
def dist(tmp_path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>")
    (d / "assets" / "app.js").write_text("console.log('app')")
    # A file outside dist that path traversal must never reach.
    (tmp_path / "secret.txt").write_text("top secret")
    return d


@pytest.fixture
def spa(dist) -> TestClient:
    """A minimal app shaped like the real one: one API route, then the static mount."""
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"pong": True}

    mount_frontend(app, dist)
    return TestClient(app)


# --- health & API ------------------------------------------------------------

def test_health_endpoint():
    assert TestClient(real_app).get("/api/health").json() == {"status": "ok"}


def test_api_routes_are_not_shadowed_by_the_static_fallback(spa):
    assert spa.get("/api/ping").json() == {"pong": True}


def test_unknown_api_path_is_404_not_index_html(spa):
    resp = spa.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert "<div id=root>" not in resp.text


def test_bare_api_path_is_404(spa):
    assert spa.get("/api").status_code == 404


# --- static UI ----------------------------------------------------------------

def test_root_serves_index(spa):
    resp = spa.get("/")
    assert resp.status_code == 200
    assert "<div id=root>" in resp.text


def test_asset_is_served_as_a_file(spa):
    resp = spa.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('app')"


def test_client_side_route_falls_back_to_index(spa):
    resp = spa.get("/crawl/some/deep/link")
    assert resp.status_code == 200
    assert "<div id=root>" in resp.text


@pytest.mark.parametrize("attack", ["..%2Fsecret.txt", "assets%2F..%2F..%2Fsecret.txt", "%2e%2e%2fsecret.txt"])
def test_path_traversal_never_reads_outside_dist(spa, attack):
    resp = spa.get(f"/{attack}")
    assert "top secret" not in resp.text


# --- CORS -------------------------------------------------------------------

@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173", "http://192.168.1.20:5173"])
def test_cors_allows_frontend_origins_on_the_dev_port(origin):
    resp = TestClient(real_app).options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_foreign_origins():
    resp = TestClient(real_app).options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in resp.headers
