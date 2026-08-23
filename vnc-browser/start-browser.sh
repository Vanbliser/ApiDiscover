#!/bin/bash
set -e

# Wait for the Xvfb socket to exist before launching the browser (no xdpyinfo
# in this image, so poll for the X11 unix socket directly instead).
DISPLAY_NUM="${DISPLAY#:}"
until [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; do
  sleep 0.2
done

# Wait for mitmproxy (see start-mitm.sh, capture_addon.py) to be up and to
# have generated its CA cert — Chrome is always pointed at it below, so
# launching before it's ready would just make every navigation fail.
MITM_CA=/root/.mitmproxy/mitmproxy-ca-cert.pem
until [ -s "$MITM_CA" ]; do
  sleep 0.2
done

CHROME_BIN=$(ls /ms-playwright/chromium-*/chrome-linux/chrome | head -n1)

# Chrome trusts mitmproxy's own generated CA — not Burp's — since mitmproxy
# is always the thing directly in front of Chrome now (see start-mitm.sh:
# Chrome -> mitmproxy -> [Burp, if configured] -> real site). Burp's CA
# (uploaded in Settings, if any) is consumed by mitmproxy itself to validate
# ITS OWN hop to Burp, not by Chrome — Chrome never talks to Burp directly
# anymore, so it never needs to know Burp's CA exists.
#
# Chromium on Linux ignores the OS trust store (update-ca-certificates) for
# its own TLS verification — it only reads user-added CAs from the NSS
# database — so this must go through certutil against ~/.pki/nssdb, not
# /usr/local/share/ca-certificates. NSS reads the DB once at process start,
# so this has to run before Chrome launches.
mkdir -p "$HOME/.pki/nssdb"
certutil -A -d "sql:$HOME/.pki/nssdb" -n mitmproxy-capture-ca -t "C,," -i "$MITM_CA" \
  && echo "start-browser: imported mitmproxy capture CA into NSS trust store" \
  || echo "start-browser: failed to import mitmproxy CA (continuing without it)" >&2

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
  --proxy-server=127.0.0.1:9224 \
  about:blank
