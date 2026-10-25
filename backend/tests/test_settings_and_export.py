"""Settings (proxy CA certificate) routes, and the export pipeline (normalize -> OpenAPI / Postman)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.models import CapturedRequest
from app.crawl.js_scan import extract_candidate_paths, looks_like_api_path
from app.export.normalize import normalize_captures, templatize_path
from app.export.openapi import build_openapi_spec
from app.export.postman import build_postman_collection
from app.main import app


# --- Settings: proxy CA certificate -------------------------------------------

@pytest.fixture
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_CA_CERT_FILE", tmp_path / "proxy_ca.pem")
    return TestClient(app)


PEM = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def test_proxy_ca_status_starts_unconfigured(settings_client):
    assert settings_client.get("/api/settings/proxy-ca-cert").json() == {"configured": False}


def test_proxy_ca_upload_accepts_pem_and_reports_configured(settings_client):
    resp = settings_client.put("/api/settings/proxy-ca-cert", files={"file": ("ca.pem", PEM, "application/x-pem-file")})
    assert resp.status_code == 200
    assert settings_client.get("/api/settings/proxy-ca-cert").json() == {"configured": True}


def test_proxy_ca_upload_rejects_non_pem(settings_client):
    resp = settings_client.put(
        "/api/settings/proxy-ca-cert",
        files={"file": ("ca.pem", b"not a certificate", "application/x-pem-file")},
    )
    assert resp.status_code == 400
    assert settings_client.get("/api/settings/proxy-ca-cert").json() == {"configured": False}


def test_proxy_ca_delete_clears_it(settings_client):
    settings_client.put("/api/settings/proxy-ca-cert", files={"file": ("ca.pem", PEM, "application/x-pem-file")})
    assert settings_client.delete("/api/settings/proxy-ca-cert").status_code == 200
    assert settings_client.get("/api/settings/proxy-ca-cert").json() == {"configured": False}


def test_recon_settings_routes_are_gone(settings_client):
    assert settings_client.get("/api/recon/providers").status_code == 404
    assert settings_client.get("/api/recon/proxy-ca-cert").status_code == 404


# --- Export pipeline ----------------------------------------------------------

def test_templatize_replaces_numeric_and_uuid_segments():
    templated, params = templatize_path("/users/42/orders/3f2504e0-4f89-41d3-9a0c-0305e82c3301")
    # Placeholder names only have to be unique within one path template.
    assert templated == "/users/{id1}/orders/{uuid2}"
    assert params == ["id1", "uuid2"]


def test_templatize_leaves_static_paths_alone():
    assert templatize_path("/api/v1/health") == ("/api/v1/health", [])


def _cap(url: str, method: str = "GET", status: int | None = 200) -> CapturedRequest:
    return CapturedRequest(method=method, url=url, status_code=status)


def test_normalize_dedupes_repeat_requests_into_one_endpoint():
    endpoints = normalize_captures([
        _cap("https://shop.example.com/api/items/1"),
        _cap("https://shop.example.com/api/items/2"),
        _cap("https://shop.example.com/api/items/3"),
    ])
    assert len(endpoints) == 1
    assert endpoints[0].method == "GET"
    assert endpoints[0].path_template == "/api/items/{id1}"


def test_normalize_keeps_methods_separate():
    endpoints = normalize_captures([
        _cap("https://shop.example.com/api/items", method="GET"),
        _cap("https://shop.example.com/api/items", method="POST", status=201),
    ])
    assert sorted(e.method for e in endpoints) == ["GET", "POST"]


def test_normalize_separates_hosts():
    endpoints = normalize_captures([
        _cap("https://a.example.com/api/x"),
        _cap("https://b.example.com/api/x"),
    ])
    assert len(endpoints) == 2


def test_openapi_spec_describes_each_endpoint():
    endpoints = normalize_captures([
        _cap("https://shop.example.com/api/items/1"),
        _cap("https://shop.example.com/api/items", method="POST", status=201),
    ])
    spec = build_openapi_spec(endpoints)
    assert spec["openapi"].startswith("3.")
    assert "/api/items/{id1}" in spec["paths"]
    assert "get" in spec["paths"]["/api/items/{id1}"]
    assert "post" in spec["paths"]["/api/items"]


def test_postman_collection_contains_one_item_per_endpoint_method():
    endpoints = normalize_captures([
        _cap("https://shop.example.com/api/items/1"),
        _cap("https://shop.example.com/api/items", method="POST", status=201),
    ])
    collection = build_postman_collection(endpoints)
    assert collection["info"]["schema"].endswith("collection.json")
    json.dumps(collection)  # must be serialisable as-is
    assert len(collection["item"]) >= 2


# --- JS scan helpers ----------------------------------------------------------

def test_js_scan_extracts_quoted_api_paths():
    source = 'fetch("/api/v2/orders"); const x = "/static/logo.png";'
    found = extract_candidate_paths(source)
    assert "/api/v2/orders" in found
    assert "/static/logo.png" not in found  # noise extension filtered out


@pytest.mark.parametrize(
    "path, expected",
    [("/api/users", True), ("/v1/items", True), ("/about-us", False), ("/settings/profile", False)],
)
def test_js_scan_api_path_heuristic(path, expected):
    assert looks_like_api_path(path) is expected
