#!/bin/bash
set -e

# Wait for the Xvfb socket to exist before launching the browser (no xdpyinfo
# in this image, so poll for the X11 unix socket directly instead).
DISPLAY_NUM="${DISPLAY#:}"
until [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; do
  sleep 0.2
done

CHROME_BIN=$(ls /ms-playwright/chromium-*/chrome-linux/chrome | head -n1)

# If the backend bind-mounted a proxy CA cert (see container.py, populated
# from the Settings-page upload), trust it before Chrome's first launch.
# Chromium on Linux ignores the OS trust store (update-ca-certificates) for
# its own TLS verification — it only reads user-added CAs from the NSS
# database — so this must go through certutil against ~/.pki/nssdb, not
# /usr/local/share/ca-certificates. NSS reads the DB once at process start,
# so this has to run before Chrome launches; a cert dropped in afterwards
# needs a container restart to take effect.
PROXY_CA_CERT=/etc/proxy-ca/ca.pem
if [ -s "$PROXY_CA_CERT" ]; then
  mkdir -p "$HOME/.pki/nssdb"
  certutil -A -d "sql:$HOME/.pki/nssdb" -n burp-proxy-ca -t "C,," -i "$PROXY_CA_CERT" \
    && echo "start-browser: imported proxy CA cert into NSS trust store" \
    || echo "start-browser: failed to import proxy CA cert (continuing without it)" >&2
fi

# Optional intercepting-proxy target (e.g. Burp Suite), set by the backend
# via -e PROXY_SERVER=host:port on `docker run` when the user supplied one at
# Launch browser time (see container.py) — decided once, at launch, since
# Chrome reads --proxy-server from net::ProxyConfigService a single time at
# process start; there is no CDP method or Playwright API to change a
# running Chrome instance's proxy afterwards. --proxy-server only affects
# the browser's own page-level networking (HTTP/HTTPS/WebSocket fetches from
# web content) — it never touches CDP (9222/9223) or anything else in this
# container, unlike an iptables-based redirect which has no way to
# distinguish "the page's traffic" from "everything else in the container."
PROXY_ARGS=()
if [ -n "$PROXY_SERVER" ]; then
  PROXY_ARGS=(--proxy-server="$PROXY_SERVER")
fi

exec "$CHROME_BIN" \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --window-position=0,0 \
  --window-size=1280,800 \
  --start-maximized \
  --no-first-run \
  --no-default-browser-check \
  "${PROXY_ARGS[@]}" \
  about:blank
