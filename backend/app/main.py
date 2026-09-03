from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_crawl import router as crawl_router
from app.api.routes_recon import router as recon_router

app = FastAPI(title="ApiDiscover")

# The frontend's dev port is configurable (see run.sh --frontend-port), so the
# allowed origin pattern must follow it rather than assume Vite's default.
_frontend_port = os.environ.get("FRONTEND_PORT", "5173")

app.add_middleware(
    CORSMiddleware,
    # localhost and 127.0.0.1 are different browser origins even though they
    # resolve to the same machine — accept both loopback forms plus any LAN
    # IP on the dev frontend's port, since this is a single-user local tool.
    allow_origin_regex=rf"https?://(localhost|127\.0\.0\.1|\[::1\]|\d{{1,3}}(\.\d{{1,3}}){{3}}):{_frontend_port}",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recon_router)
app.include_router(crawl_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
