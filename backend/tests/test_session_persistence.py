"""Saved App Crawl sessions: on-disk storage, and exclusion changes persisting to session.json."""

from __future__ import annotations

from app.core import sessions_store
from app.core.models import CapturedRequest
from app.crawl.session import CrawlSession


def _request(url: str, method: str = "GET") -> CapturedRequest:
    return CapturedRequest(method=method, url=url, status_code=200)


# --- sessions_store -----------------------------------------------------------

def test_init_creates_meta_and_profile_dir(isolated_storage):
    meta = sessions_store.init_saved_session("s1", "https://example.com/app", "proxy:8080")
    assert meta.label.startswith("example.com")
    assert sessions_store.profile_dir("s1").is_dir()
    loaded = sessions_store.load_meta("s1")
    assert loaded.start_url == "https://example.com/app"
    assert loaded.proxy_server == "proxy:8080"


def test_load_meta_missing_is_none(isolated_storage):
    assert sessions_store.load_meta("nope") is None


def test_captured_requests_round_trip_in_order(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    sessions_store.append_captured("s1", _request("https://example.com/a"))
    sessions_store.append_captured("s1", _request("https://example.com/b", method="POST"))
    loaded = sessions_store.load_captured("s1")
    assert [(c.method, c.url) for c in loaded] == [
        ("GET", "https://example.com/a"),
        ("POST", "https://example.com/b"),
    ]


def test_corrupt_trailing_line_is_skipped_not_fatal(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    sessions_store.append_captured("s1", _request("https://example.com/a"))
    # Simulates the process dying mid-append.
    with open(sessions_store.captured_path("s1"), "a") as f:
        f.write('{"method": "GET", "url": "https://exa')
    loaded = sessions_store.load_captured("s1")
    assert [c.url for c in loaded] == ["https://example.com/a"]


def test_count_captured_ignores_blank_lines(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    for i in range(3):
        sessions_store.append_captured("s1", _request(f"https://example.com/{i}"))
    with open(sessions_store.captured_path("s1"), "a") as f:
        f.write("\n\n")
    assert sessions_store.count_captured("s1") == 3


def test_count_captured_without_history_is_zero(isolated_storage):
    assert sessions_store.count_captured("never-saved") == 0


def test_list_saved_sessions_skips_non_session_entries(isolated_storage):
    sessions_store.init_saved_session("a", "https://a.example", None)
    sessions_store.init_saved_session("b", "https://b.example", None)
    (sessions_store.SESSIONS_ROOT / "stray-file.txt").write_text("not a session")
    (sessions_store.SESSIONS_ROOT / "no-meta-dir").mkdir()
    ids = sorted(m.session_id for m in sessions_store.list_saved_sessions())
    assert ids == ["a", "b"]


def test_delete_removes_everything(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    sessions_store.append_captured("s1", _request("https://example.com/a"))
    sessions_store.delete_saved_session("s1")
    assert not sessions_store.session_dir("s1").exists()


# --- CrawlSession exclusions persist for saved sessions only ------------------

def test_saved_session_exclusions_are_written_to_session_json(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    session = CrawlSession("s1", save_session=True)

    session.exclude_host("analytics.example.com")
    session.exclude_endpoint("get", "example.com", "/api/{id}")
    session.exclude_extension(".PNG")
    session.exclude_method("options")

    meta = sessions_store.load_meta("s1")
    assert meta.excluded_hosts == ["analytics.example.com"]
    assert meta.excluded_endpoints == [["GET", "example.com", "/api/{id}"]]
    assert meta.excluded_extensions == ["png"]
    assert meta.excluded_methods == ["OPTIONS"]


def test_include_reverses_an_exclusion_on_disk(isolated_storage):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    session = CrawlSession("s1", save_session=True)
    session.exclude_host("x.example.com")
    session.include_host("x.example.com")
    assert sessions_store.load_meta("s1").excluded_hosts == []


def test_ephemeral_session_writes_nothing_to_disk(isolated_storage):
    session = CrawlSession("ephemeral", save_session=False)
    session.exclude_host("x.example.com")
    assert sessions_store.load_meta("ephemeral") is None
    assert not sessions_store.session_dir("ephemeral").exists()


async def test_resume_restores_exclusions_and_history(isolated_storage, monkeypatch):
    sessions_store.init_saved_session("s1", "https://example.com", None)
    sessions_store.append_captured("s1", _request("https://example.com/a"))
    CrawlSession("s1", save_session=True).exclude_host("noise.example.com")

    async def no_launch(self, start_url, pre_navigate=None):
        return None  # no Docker/browser in this test

    monkeypatch.setattr(CrawlSession, "_launch", no_launch)

    resumed = CrawlSession("s1", save_session=True)
    await resumed.resume("https://example.com")

    assert [c.url for c in resumed.captured] == ["https://example.com/a"]
    assert resumed.excluded_hosts == {"noise.example.com"}
