from __future__ import annotations

import asyncio
import socket

VNC_BROWSER_IMAGE = "apidiscover-vnc-browser"

# Serializes port allocation + `docker run` across concurrent session starts.
# Without this, two start() calls could both read the same "free" port from
# the OS before either has actually bound it via Docker (see _reserve_ports).
_launch_lock = asyncio.Lock()

MAX_LAUNCH_ATTEMPTS = 3


def _reserve_ports(count: int) -> tuple[list[int], list[socket.socket]]:
    """
    Bind `count` sockets to OS-assigned free ports and return both the port
    numbers and the still-open sockets. Keeping the sockets open until right
    before `docker run` executes shrinks the gap between "the OS told us this
    port is free" and "Docker actually claims it" — the main way two
    concurrent session starts could otherwise be handed the same port.
    """
    sockets = []
    ports = []
    for _ in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("", 0))
        sockets.append(s)
        ports.append(s.getsockname()[1])
    return ports, sockets


def _release_ports(sockets: list[socket.socket]) -> None:
    for s in sockets:
        s.close()


class VncBrowserContainer:
    """
    Launches one Docker container running Xvfb + Chromium + x11vnc + noVNC for a
    single crawl session. The human interacts with the browser directly through
    the noVNC web client (served on `novnc_port`); the backend drives the SAME
    browser autonomously via CDP (`cdp_port`) once the walker takes over.

    CDP is reached through an nginx proxy inside the container (internal port
    9223) that rewrites the Host header to 127.0.0.1:9222 before forwarding to
    Chrome, and rewrites the webSocketDebuggerUrl in Chrome's /json responses
    from 9222 to the real host-published port — so Playwright's follow-up
    WebSocket connection also goes through the proxy correctly. That published
    port is only known once we've picked it (see _reserve_ports), so it's
    passed into the container as CDP_HOST_PORT and nginx's config is rendered
    from a template at container startup (see start-nginx.sh) rather than
    baked into the image — that's what makes concurrent sessions possible,
    each container renders its own config for its own dynamically-chosen port.
    """

    def __init__(self, container_name: str) -> None:
        self.container_name = container_name
        self.novnc_port: int | None = None
        self.cdp_port: int | None = None

    async def start(self) -> None:
        last_error: str | None = None

        for attempt in range(1, MAX_LAUNCH_ATTEMPTS + 1):
            async with _launch_lock:
                (novnc_port, cdp_port), sockets = _reserve_ports(2)

                proc = await asyncio.create_subprocess_exec(
                    "docker", "run", "-d", "--rm",
                    "--name", self.container_name,
                    "-e", f"CDP_HOST_PORT={cdp_port}",
                    "-p", f"{novnc_port}:6080",
                    "-p", f"{cdp_port}:9223",
                    VNC_BROWSER_IMAGE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # Only release the ports once `docker run` has actually been
                # issued — this is the "hold the socket open" half of the fix.
                _release_ports(sockets)
                _, stderr = await proc.communicate()

            if proc.returncode == 0:
                self.novnc_port = novnc_port
                self.cdp_port = cdp_port
                await self._wait_for_cdp()
                return

            last_error = stderr.decode()
            if "address already in use" not in last_error.lower() and "port is already allocated" not in last_error.lower():
                break  # not a port race — retrying with new ports won't help

        raise RuntimeError(
            f"failed to start VNC browser container after {attempt} attempt(s): {last_error}"
        )

    async def _wait_for_cdp(self, timeout: float = 30.0) -> None:
        import httpx

        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    resp = await client.get(f"http://localhost:{self.cdp_port}/json/version", timeout=1.0)
                    if resp.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        raise TimeoutError("VNC browser container did not expose CDP in time")

    @property
    def cdp_endpoint(self) -> str:
        assert self.cdp_port is not None
        return f"http://localhost:{self.cdp_port}"

    @property
    def novnc_url(self) -> str:
        assert self.novnc_port is not None
        return f"http://localhost:{self.novnc_port}/vnc.html?autoconnect=true&resize=scale"

    async def stop(self) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "stop", self.container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
