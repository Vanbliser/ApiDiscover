from __future__ import annotations

import asyncio
from typing import Callable

import httpx

from app.core.models import CapturedRequest

POLL_INTERVAL_SECONDS = 1.0


class CapturePoller:
    """
    Polls the mitmproxy capture API running inside a session's container
    (see vnc-browser/capture_addon.py) and forwards new records to a
    callback, translated into this app's CapturedRequest shape.

    This is the session's actual capture mechanism — mitmproxy sees every
    HTTP(S) request Chrome sends, independent of Playwright/CDP attach
    state and independent of manual vs. autonomous control, closing the gap
    where page.on("response") silently missed requests that started before
    Playwright's CDP session finished attaching to an already-running
    Chrome instance.
    """

    def __init__(self, capture_api_endpoint: str, on_capture: Callable[[CapturedRequest], None]) -> None:
        self._endpoint = capture_api_endpoint
        self._on_capture = on_capture
        self._last_id = 0
        self._task: asyncio.Task | None = None
        self._stopped = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self) -> None:
        async with httpx.AsyncClient() as client:
            while not self._stopped:
                try:
                    resp = await client.get(
                        f"{self._endpoint}/captured",
                        params={"since_id": self._last_id},
                        timeout=5.0,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for record in data.get("captured", []):
                        self._last_id = max(self._last_id, record["id"])
                        captured = CapturedRequest(
                            method=record["method"],
                            url=record["url"],
                            request_headers=record.get("request_headers", {}),
                            request_body=record.get("request_body"),
                            status_code=record.get("status_code"),
                            response_headers=record.get("response_headers", {}),
                            response_body_sample=record.get("response_body_sample"),
                            resource_type=record.get("resource_type"),
                        )
                        self._on_capture(captured)
                except (httpx.HTTPError, KeyError, ValueError):
                    # Transient — the container may still be starting mitmproxy,
                    # or briefly unreachable between requests; next poll retries.
                    pass
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
