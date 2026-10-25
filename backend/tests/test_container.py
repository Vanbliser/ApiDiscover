"""VncBrowserContainer: what `docker run` is asked to publish. No real container is started."""

from __future__ import annotations

import pytest

from app.crawl import container as container_module
from app.crawl.container import VncBrowserContainer


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        return b"", b""


@pytest.fixture
def docker_calls(monkeypatch):
    """Records every `docker` argv instead of running it, and skips the CDP readiness wait."""
    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProcess()

    async def no_wait(self, timeout=30.0):
        return None

    monkeypatch.setattr(container_module.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(VncBrowserContainer, "_wait_for_cdp", no_wait)
    return calls


def _published_ports(argv) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "-p"]


async def test_all_session_ports_are_published_on_loopback_only(docker_calls):
    c = VncBrowserContainer(container_name="apidiscover-crawl-test")
    await c.start()

    argv = docker_calls[0]
    published = _published_ports(argv)
    assert len(published) == 3, published
    for mapping in published:
        assert mapping.startswith("127.0.0.1:"), f"port published beyond loopback: {mapping}"


async def test_published_ports_match_the_recorded_session_ports(docker_calls):
    c = VncBrowserContainer(container_name="apidiscover-crawl-test")
    await c.start()

    published = _published_ports(docker_calls[0])
    assert f"127.0.0.1:{c.novnc_port}:6080" in published
    assert f"127.0.0.1:{c.cdp_port}:9223" in published
    assert f"127.0.0.1:{c.capture_port}:9225" in published


async def test_container_no_longer_hands_out_a_localhost_url(docker_calls):
    c = VncBrowserContainer(container_name="apidiscover-crawl-test")
    await c.start()
    assert not hasattr(c, "novnc_url")


async def test_session_containers_resolve_host_docker_internal(docker_calls):
    c = VncBrowserContainer(container_name="apidiscover-crawl-test")
    await c.start()
    argv = docker_calls[0]
    assert argv[argv.index("--add-host") + 1] == "host.docker.internal:host-gateway"


async def test_reachability_check_uses_the_same_host_alias(monkeypatch):
    from app.crawl.container import check_proxy_reachable

    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProcess()

    monkeypatch.setattr(container_module.asyncio, "create_subprocess_exec", fake_exec)
    ok, _ = await check_proxy_reachable("host.docker.internal", 8080)
    assert ok
    argv = calls[0]
    assert argv[argv.index("--add-host") + 1] == "host.docker.internal:host-gateway"
