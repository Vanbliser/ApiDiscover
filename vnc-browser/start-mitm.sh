#!/bin/bash
# Starts mitmdump as the container-internal capture proxy Chrome is always
# pointed at (see start-browser.sh). This is the actual capture point for
# App Crawl sessions — see capture_addon.py for why capture lives here
# instead of in Playwright.
#
# Two modes, chosen by whether PROXY_SERVER is set (the user's Burp target,
# passed in the same way it was for the old direct-to-Burp approach — see
# container.py):
#   - PROXY_SERVER set:   mitmproxy forwards everything to that upstream
#     proxy (Burp) after logging it, so Burp's own Proxy history and this
#     app's captured-API list see the same traffic.
#   - PROXY_SERVER unset: mitmproxy connects directly to the real origin
#     after logging — capture still works with no Burp involved at all,
#     closing the "manual control isn't captured" gap the old
#     Playwright-based approach had.
set -e

mkdir -p "$HOME/.mitmproxy"

MITM_ARGS=(
  -p 9224
  -s /usr/local/bin/capture_addon.py
  --set confdir="$HOME/.mitmproxy"
)

if [ -n "$PROXY_SERVER" ]; then
  # mitmproxy's own upstream-trust option (ssl_verify_upstream_trusted_ca)
  # REPLACES its default trusted-CA set rather than adding to it (see
  # https://github.com/mitmproxy/mitmproxy/issues/7096) — so if we only
  # pointed it at Burp's CA, mitmproxy would stop trusting the public CAs
  # it also needs whenever it talks to anything that isn't Burp. Burp is
  # the only upstream target this hop ever has here, so that's moot for
  # THIS specific hop, but concatenating with the system bundle is cheap
  # insurance against that surprising-replace behavior either way.
  COMBINED_CA=/etc/proxy-ca/combined-upstream-ca.pem
  cat /etc/ssl/certs/ca-certificates.crt > "$COMBINED_CA"
  if [ -s /etc/proxy-ca/ca.pem ]; then
    cat /etc/proxy-ca/ca.pem >> "$COMBINED_CA"
  else
    echo "start-mitm: PROXY_SERVER is set but no Burp CA cert is configured in Settings" >&2
    echo "start-mitm: the hop from this proxy to $PROXY_SERVER will fail TLS validation" >&2
  fi
  MITM_ARGS+=(--mode "upstream:http://$PROXY_SERVER")
  MITM_ARGS+=(--set "ssl_verify_upstream_trusted_ca=$COMBINED_CA")
  echo "start-mitm: forwarding captured traffic to upstream proxy $PROXY_SERVER"
else
  echo "start-mitm: no upstream proxy configured, connecting directly to origin"
fi

exec mitmdump "${MITM_ARGS[@]}"
