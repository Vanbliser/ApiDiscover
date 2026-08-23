"""
mitmproxy addon: the actual capture point for App Crawl sessions.

Runs inside the vnc-browser container as the proxy Chrome is launched
pointed at (see start-browser.sh, start-mitm.sh). Every request/response
mitmproxy sees — regardless of whether Chrome/CDP/Playwright is even
attached, and regardless of manual vs. autonomous crawl control — gets
logged here. This replaces relying on Playwright's page.on("response"),
which turned out to silently miss requests that start before Playwright's
CDP session finishes attaching to an already-running Chrome (a documented
Playwright/CDP timing race, not fixable from the Playwright side).

Captured flows are kept in memory and served over a plain HTTP endpoint on
CAPTURE_API_PORT, polled by the backend (see backend/app/crawl/capture_client.py)
instead of tailing a log file across the container boundary.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mitmproxy import http

CAPTURE_API_PORT = 9225
MAX_BODY_SAMPLE = 2000
MAX_CAPTURED = 20000  # simple ring-buffer cap so a very long session doesn't grow unbounded

_lock = threading.Lock()
_captured: list[dict] = []
_next_id = 1


def _flow_to_record(flow: http.HTTPFlow) -> dict:
    global _next_id
    req = flow.request
    resp = flow.response

    req_body = None
    try:
        req_body = req.get_text(strict=False)
    except Exception:
        pass

    resp_body_sample = None
    if resp is not None:
        try:
            text = resp.get_text(strict=False)
            if text is not None:
                resp_body_sample = text[:MAX_BODY_SAMPLE]
        except Exception:
            pass

    with _lock:
        record_id = _next_id
        _next_id += 1

    return {
        "id": record_id,
        "method": req.method,
        "url": req.pretty_url,
        "request_headers": dict(req.headers),
        "request_body": req_body,
        "status_code": resp.status_code if resp is not None else None,
        "response_headers": dict(resp.headers) if resp is not None else {},
        "response_body_sample": resp_body_sample,
        # mitmproxy has no notion of Playwright's resourceType (script vs
        # xhr vs document) since it operates below the browser entirely —
        # every HTTP request Chrome sends is captured uniformly, which is
        # the whole point of moving capture here.
        "resource_type": None,
    }


class CaptureLogger:
    def response(self, flow: http.HTTPFlow) -> None:
        record = _flow_to_record(flow)
        with _lock:
            _captured.append(record)
            if len(_captured) > MAX_CAPTURED:
                del _captured[: len(_captured) - MAX_CAPTURED]

    def error(self, flow: http.HTTPFlow) -> None:
        # A flow that never got a response (connection reset, timeout,
        # blocked by an upstream proxy, etc.) — still recorded, with
        # status_code left null, since "the browser sent this request" is
        # true regardless of whether anything answered. This is exactly the
        # class of request the old Playwright-based capture could drop
        # silently; here it's still visible.
        record = _flow_to_record(flow)
        with _lock:
            _captured.append(record)
            if len(_captured) > MAX_CAPTURED:
                del _captured[: len(_captured) - MAX_CAPTURED]


class _CaptureApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - matches base signature
        pass  # silence default stderr access logging, mitmdump's own log is enough

    def do_GET(self) -> None:
        if self.path.startswith("/captured"):
            since_id = 0
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for part in query.split("&"):
                    if part.startswith("since_id="):
                        try:
                            since_id = int(part.split("=", 1)[1])
                        except ValueError:
                            since_id = 0
            with _lock:
                results = [r for r in _captured if r["id"] > since_id]
            body = json.dumps({"captured": results}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def _run_capture_api() -> None:
    # 0.0.0.0, not 127.0.0.1 — this port is published externally (see
    # container.py's -p mapping) so the backend can poll it from outside the
    # container; a loopback-only bind would refuse/reset every connection
    # arriving through Docker's port forwarding, which lands on the
    # container's real interface, not literal loopback.
    server = ThreadingHTTPServer(("0.0.0.0", CAPTURE_API_PORT), _CaptureApiHandler)
    server.serve_forever()


threading.Thread(target=_run_capture_api, daemon=True).start()

addons = [CaptureLogger()]
