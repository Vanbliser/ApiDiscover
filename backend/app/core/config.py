from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# A CA certificate is a public document by design (no private key involved),
# so it's stored as a plain PEM file — there's nothing at rest here that needs
# protecting. Bind-mounted read-only into a session's container when the user
# has uploaded one — see container.py.
PROXY_CA_CERT_FILE = DATA_DIR / "proxy_ca.pem"


def get_proxy_ca_cert_path() -> str | None:
    return str(PROXY_CA_CERT_FILE) if PROXY_CA_CERT_FILE.exists() else None


def set_proxy_ca_cert(pem_bytes: bytes) -> None:
    PROXY_CA_CERT_FILE.write_bytes(pem_bytes)


def clear_proxy_ca_cert() -> None:
    PROXY_CA_CERT_FILE.unlink(missing_ok=True)
