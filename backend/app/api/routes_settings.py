from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.config import clear_proxy_ca_cert, get_proxy_ca_cert_path, set_proxy_ca_cert

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/proxy-ca-cert")
def get_proxy_ca_cert_status():
    """
    Whether an intercepting-proxy CA cert (e.g. Burp Suite's) is currently
    configured — used by the App Crawl panel to know whether HTTPS traffic
    routed through a proxy will actually validate cleanly for a *new*
    session, versus needing to be uploaded first. Applies at container
    start (see session.py) — uploading one now doesn't retroactively
    affect already-running sessions.
    """
    return {"configured": get_proxy_ca_cert_path() is not None}


@router.put("/proxy-ca-cert")
async def upload_proxy_ca_cert(file: UploadFile):
    body = await file.read()
    if not body.strip().startswith(b"-----BEGIN CERTIFICATE-----"):
        raise HTTPException(status_code=400, detail="not a PEM certificate (expected a -----BEGIN CERTIFICATE----- block)")
    set_proxy_ca_cert(body)
    return {"status": "ok"}


@router.delete("/proxy-ca-cert")
def delete_proxy_ca_cert():
    clear_proxy_ca_cert()
    return {"status": "ok"}
