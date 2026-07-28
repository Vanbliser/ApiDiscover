FROM mcr.microsoft.com/playwright:v1.47.0-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Africa/Lagos

# Some networks block/throttle plain HTTP (port 80) to the Ubuntu package
# mirrors while allowing HTTPS through fine — force apt to use https:// so
# `apt-get update` doesn't hang waiting on a blocked port.
RUN find /etc/apt/ -name "*.list" -o -name "*.sources" | xargs -r sed -i 's|http://|https://|g'

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    websockify \
    supervisor \
    nginx \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

ENV DISPLAY=:99
ENV SCREEN_RESOLUTION=1280x800x24

RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY start-browser.sh /usr/local/bin/start-browser.sh
COPY start-nginx.sh /usr/local/bin/start-nginx.sh
RUN chmod +x /usr/local/bin/start-browser.sh /usr/local/bin/start-nginx.sh

# supervisord runs everything as root, so fluxbox reads root's per-user
# config. The apps rule makes Chromium's window borderless and pinned to
# fill the whole virtual display, and the toolbar is disabled — there's only
# ever one window and no window management needed, so this removes fluxbox's
# title bar/restore control and taskbar strip entirely rather than leaving
# something the user could misclick or that eats into the visible display.
RUN mkdir -p /root/.fluxbox
COPY fluxbox-apps /root/.fluxbox/apps
COPY fluxbox-init /root/.fluxbox/init

RUN rm -f /etc/nginx/sites-enabled/default
COPY cdp-proxy.conf.template /etc/nginx/conf.d/cdp-proxy.conf.template

EXPOSE 6080 9223

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
