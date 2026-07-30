from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_crawl import router as crawl_router
from app.api.routes_recon import router as recon_router

app = FastAPI(title="ApiDiscover")

app.add_middleware(
    CORSMiddleware,
    # localhost and 127.0.0.1 are different browser origins even though they
    # resolve to the same machine — accept both loopback forms plus any LAN
    # IP on the dev frontend's port, since this is a single-user local tool.
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\]|\d{1,3}(\.\d{1,3}){3}):5173",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recon_router)
app.include_router(crawl_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
