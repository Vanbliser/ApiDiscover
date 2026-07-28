from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import BaseModel

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
KEY_FILE = DATA_DIR / "secret.key"
PROVIDER_CONFIG_FILE = DATA_DIR / "provider_config.enc"


def _load_or_create_fernet_key() -> Fernet:
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        KEY_FILE.chmod(0o600)
    return Fernet(key)


class ProviderConfig(BaseModel):
    name: str
    enabled: bool = False
    api_key: str | None = None
    cookies: dict[str, str] = {}
    extra: dict[str, str] = {}


class ProviderConfigStore:
    """Encrypted-at-rest store for third-party recon provider settings (API keys, etc.)."""

    def __init__(self) -> None:
        self._fernet = _load_or_create_fernet_key()
        self._configs: dict[str, ProviderConfig] = {}
        self._load()

    def _load(self) -> None:
        if not PROVIDER_CONFIG_FILE.exists():
            return
        raw = self._fernet.decrypt(PROVIDER_CONFIG_FILE.read_bytes())
        data = json.loads(raw)
        self._configs = {k: ProviderConfig(**v) for k, v in data.items()}

    def _save(self) -> None:
        data = {k: v.model_dump() for k, v in self._configs.items()}
        raw = json.dumps(data).encode()
        PROVIDER_CONFIG_FILE.write_bytes(self._fernet.encrypt(raw))
        PROVIDER_CONFIG_FILE.chmod(0o600)

    def get(self, name: str) -> ProviderConfig | None:
        return self._configs.get(name)

    def list(self) -> list[ProviderConfig]:
        return list(self._configs.values())

    def set(self, config: ProviderConfig) -> None:
        self._configs[config.name] = config
        self._save()


provider_config_store = ProviderConfigStore()
