#!/bin/bash
set -e

# Wait for the Xvfb socket to exist before launching the browser (no xdpyinfo
# in this image, so poll for the X11 unix socket directly instead).
DISPLAY_NUM="${DISPLAY#:}"
until [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; do
  sleep 0.2
done

CHROME_BIN=$(ls /ms-playwright/chromium-*/chrome-linux/chrome | head -n1)

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
  about:blank
