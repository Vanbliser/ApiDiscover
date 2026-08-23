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
    libnss3-tools \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# mitmproxy is the actual capture point for App Crawl sessions (see
# capture_addon.py) — Chrome is always launched pointed at it
# (start-browser.sh), rather than relying on Playwright/CDP events, which
# turned out to silently miss requests that start before Playwright's CDP
# session finishes attaching to an already-running Chrome instance.
RUN pip3 install --no-cache-dir mitmproxy==11.0.2

ENV DISPLAY=:99
ENV SCREEN_RESOLUTION=1280x800x24

RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY start-browser.sh /usr/local/bin/start-browser.sh
COPY start-nginx.sh /usr/local/bin/start-nginx.sh
COPY start-mitm.sh /usr/local/bin/start-mitm.sh
COPY capture_addon.py /usr/local/bin/capture_addon.py
RUN chmod +x /usr/local/bin/start-browser.sh /usr/local/bin/start-nginx.sh /usr/local/bin/start-mitm.sh

# supervisord runs everything as root, so fluxbox reads root's per-user
# config. The apps rule makes Chromium's window borderless and pinned to
# fill the whole virtual display, and the toolbar is disabled — there's only
# ever one window and no window management needed, so this removes fluxbox's
# title bar/restore control and taskbar strip entirely rather than leaving
# something the user could misclick or that eats into the visible display.
RUN mkdir -p /root/.fluxbox
COPY fluxbox-apps /root/.fluxbox/apps
COPY fluxbox-init /root/.fluxbox/init

# Mount point for host-uploaded files (bind-mounted per-session by the
# backend — see container.py). Getting Chromium's native file-picker (opened
# by a page's <input type=file>) to default to this folder isn't controlled
# by one single documented switch, so this is belt-and-suspenders across the
# three mechanisms that plausibly influence it:
#  - Chromium's DownloadDirectory enterprise policy: guaranteed for the
#    Save/download dialog, and observed in practice to also seed the Open
#    dialog's starting folder since both fall back to the same "last used
#    directory" preference when no directory-specific history exists yet.
#  - XDG_DOWNLOAD_DIR: GTK's file chooser (what Chromium's Open dialog
#    actually renders on Linux) consults the XDG user-dirs "Downloads"
#    location as one of its default shortcuts.
#  - A GTK bookmark for the same path, so it's one click away in the
#    sidebar even on a build/version where neither of the above applies.
RUN mkdir -p /root/Uploads && \
    mkdir -p /root/.config/gtk-3.0 /root/.config /etc/opt/chrome/policies/managed && \
    printf 'file:///root/Uploads Uploads\n' > /root/.config/gtk-3.0/bookmarks && \
    printf 'XDG_DOWNLOAD_DIR="/root/Uploads"\n' > /root/.config/user-dirs.dirs && \
    printf '{"DownloadDirectory": "/root/Uploads", "PromptForDownloadLocation": false}\n' \
        > /etc/opt/chrome/policies/managed/uploads.json
ENV XDG_DOWNLOAD_DIR=/root/Uploads

RUN rm -f /etc/nginx/sites-enabled/default
COPY cdp-proxy.conf.template /etc/nginx/conf.d/cdp-proxy.conf.template

# Mount point for an optional Burp Suite (or other intercepting proxy) CA
# certificate, bind-mounted per-session by the backend when the user has
# uploaded one in Settings. Consumed by start-mitm.sh to validate mitmproxy's
# OWN outbound hop to Burp (see start-mitm.sh) — Chrome no longer talks to
# Burp directly, so it no longer needs this cert; it trusts mitmproxy's own
# generated CA instead (see start-browser.sh).
RUN mkdir -p /etc/proxy-ca

EXPOSE 6080 9223 9225

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
