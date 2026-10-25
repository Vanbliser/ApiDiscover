"""
Serves the built frontend (`npm run build` output) from the backend, so the UI
and /api share one origin and one port in production.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """
    Adds a catch-all GET route that serves files from `dist`, falling back to
    index.html so client-side routing works. Must be called after the API
    routers are included, so /api/* requests always match their real routes
    first; anything under /api/ that is still unmatched gets a 404 here, never
    the HTML fallback.
    """
    dist = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
