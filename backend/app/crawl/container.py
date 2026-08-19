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


async def check_proxy_reachable(proxy_host: str, proxy_port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Probes whether `proxy_host:proxy_port` is reachable from *inside a
    container on this same Docker network* — not from the backend process's
    own host, since addresses like host.docker.internal only resolve inside
    a container and would otherwise always fail this check. Runs a
    throwaway container (reusing the vnc-browser image rather than pulling
    something extra just for this) that does a plain TCP connect test, so a
    user can verify their proxy address *before* committing to it at
    Launch browser time — this is the one time such a check is possible,
    since --proxy-server is fixed for the life of the container once it
    starts (see VncBrowserContainer.proxy_server).
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "run", "--rm", VNC_BROWSER_IMAGE,
        "bash", "-c",
        f'timeout {timeout} bash -c "exec 3<>/dev/tcp/{proxy_host}/{proxy_port}" 2>&1',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return True, f"{proxy_host}:{proxy_port} is reachable"
    detail = (stdout + stderr).decode().strip()
    return False, f"could not reach {proxy_host}:{proxy_port}" + (f" ({detail})" if detail else "")


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

    def __init__(
        self,
        container_name: str,
        uploads_dir: str | None = None,
        proxy_ca_cert_path: str | None = None,
        proxy_server: str | None = None,
    ) -> None:
        self.container_name = container_name
        self.uploads_dir = uploads_dir
        # Host-side path to a PEM CA cert (e.g. Burp's) to trust inside the
        # container, if the user has uploaded one in Settings — see
        # start-browser.sh, which imports it into NSS before Chrome launches.
        self.proxy_ca_cert_path = proxy_ca_cert_path
        # "host:port" of an intercepting proxy (e.g. Burp Suite) to pass to
        # Chrome as --proxy-server, decided once at launch. Chrome reads its
        # proxy config once from net::ProxyConfigService at process start —
        # there's no CDP method or Playwright API to change it on a running
        # browser — so this can't be toggled mid-session; changing it means
        # stopping this session and starting a new one with a different
        # value. In exchange, --proxy-server only ever touches the browser's
        # own page-level networking, never CDP/VNC/anything else in the
        # container, which a network-layer redirect (iptables) can't
        # guarantee without also risking those unrelated things.
        self.proxy_server = proxy_server
        self.novnc_port: int | None = None
        self.cdp_port: int | None = None

    async def start(self) -> None:
        last_error: str | None = None

        for attempt in range(1, MAX_LAUNCH_ATTEMPTS + 1):
            async with _launch_lock:
                (novnc_port, cdp_port), sockets = _reserve_ports(2)

                args = [
                    "docker", "run", "-d", "--rm",
                    "--name", self.container_name,
                    "-e", f"CDP_HOST_PORT={cdp_port}",
                    "-p", f"{novnc_port}:6080",
                    "-p", f"{cdp_port}:9223",
                ]
                if self.proxy_server is not None:
                    args += ["-e", f"PROXY_SERVER={self.proxy_server}"]
                if self.uploads_dir is not None:
                    # Host-side directory the backend writes uploaded files
                    # into (see routes_crawl.py's upload endpoint) — bind
                    # mounted rather than `docker cp`'d in, so large uploads
                    # count against server disk, not the container's
                    # writable layer.
                    args += ["-v", f"{self.uploads_dir}:/root/Uploads"]
                if self.proxy_ca_cert_path is not None:
                    args += ["-v", f"{self.proxy_ca_cert_path}:/etc/proxy-ca/ca.pem:ro"]
                args.append(VNC_BROWSER_IMAGE)

                proc = await asyncio.create_subprocess_exec(
                    *args,
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
