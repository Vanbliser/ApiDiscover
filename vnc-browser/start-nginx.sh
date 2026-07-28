#!/bin/bash
set -e

: "${CDP_HOST_PORT:?CDP_HOST_PORT must be set (the host port Docker published for container port 9223)}"

envsubst '${CDP_HOST_PORT}' \
  < /etc/nginx/conf.d/cdp-proxy.conf.template \
  > /etc/nginx/conf.d/cdp-proxy.conf

exec /usr/sbin/nginx -g "daemon off;"
