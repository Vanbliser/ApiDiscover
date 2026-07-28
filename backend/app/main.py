from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_crawl import router as crawl_router
from app.api.routes_recon import router as recon_router

app = FastAPI(title="ApiDiscover")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recon_router)
app.include_router(crawl_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
