from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.config import DATA_DIR
from app.core.models import CapturedRequest

# Saved App Crawl sessions live here, one subdirectory per session_id:
#   {id}/session.json     metadata + exclusions, rewritten in full (changes rarely)
#   {id}/captured.jsonl   one CapturedRequest per line, append-only (changes per capture)
#   {id}/profile/         Chrome's --user-data-dir, bind-mounted into the container
# Unlike provider_config.enc, none of this is sensitive-at-rest by nature (it's the
# user's own crawl traffic against their own target), so no encryption here — same
# reasoning as proxy_ca.pem in config.py.
SESSIONS_ROOT = DATA_DIR / "sessions"


class SavedSessionMeta(BaseModel):
    session_id: str
    label: str
    start_url: str
    proxy_server: str | None = None
    created_at: str
    updated_at: str
    excluded_hosts: list[str] = Field(default_factory=list)
    # (method, host, path_template) triples — plain lists since tuples aren't JSON-native.
    excluded_endpoints: list[list[str]] = Field(default_factory=list)
    excluded_extensions: list[str] = Field(default_factory=list)
    excluded_methods: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_dir(session_id: str) -> Path:
    return SESSIONS_ROOT / session_id


def profile_dir(session_id: str) -> Path:
    return session_dir(session_id) / "profile"


def captured_path(session_id: str) -> Path:
    return session_dir(session_id) / "captured.jsonl"


def meta_path(session_id: str) -> Path:
    return session_dir(session_id) / "session.json"


def _label_for(start_url: str, created_at: str) -> str:
    from urllib.parse import urlsplit

    host = urlsplit(start_url).netloc or start_url
    return f"{host} — {created_at}"


def init_saved_session(session_id: str, start_url: str, proxy_server: str | None) -> SavedSessionMeta:
    """Creates session_dir + profile_dir and writes the initial session.json. Called
    once, from CrawlSession.start(), only when save_session=True."""
    session_dir(session_id).mkdir(parents=True, exist_ok=True)
    profile_dir(session_id).mkdir(parents=True, exist_ok=True)
    now = _now()
    meta = SavedSessionMeta(
        session_id=session_id,
        label=_label_for(start_url, now),
        start_url=start_url,
        proxy_server=proxy_server,
        created_at=now,
        updated_at=now,
    )
    write_meta(meta)
    return meta


def write_meta(meta: SavedSessionMeta) -> None:
    meta.updated_at = _now()
    meta_path(meta.session_id).write_text(meta.model_dump_json())


def load_meta(session_id: str) -> SavedSessionMeta | None:
    path = meta_path(session_id)
    if not path.exists():
        return None
    return SavedSessionMeta(**json.loads(path.read_text()))


def append_captured(session_id: str, captured: CapturedRequest) -> None:
    with open(captured_path(session_id), "a") as f:
        f.write(captured.model_dump_json())
        f.write("\n")


def load_captured(session_id: str) -> list[CapturedRequest]:
    path = captured_path(session_id)
    if not path.exists():
        return []
    results: list[CapturedRequest] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(CapturedRequest(**json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                # A half-written last line (e.g. process died mid-append) shouldn't
                # take down loading everything captured before it.
                continue
    return results


def count_captured(session_id: str) -> int:
    """Cheap raw line count — not a deduplicated endpoint count, just how many
    requests were ever captured. Used by the saved-sessions list, where computing
    a real endpoint count would mean normalizing every saved session's full
    history on every list call."""
    path = captured_path(session_id)
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for line in f if line.strip())


def list_saved_sessions() -> list[SavedSessionMeta]:
    if not SESSIONS_ROOT.exists():
        return []
    metas: list[SavedSessionMeta] = []
    for child in sorted(SESSIONS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        meta = load_meta(child.name)
        if meta is not None:
            metas.append(meta)
    return metas


def delete_saved_session(session_id: str) -> None:
    shutil.rmtree(session_dir(session_id), ignore_errors=True)
