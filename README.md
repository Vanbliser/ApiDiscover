# ApiDiscover

An API endpoint discovery tool built for an **external, attacker's-eye view** of your
application. It finds the endpoints that your applications calls and packages them into an OpenAPI spec and a Postman
collection.

The app is built around one mode, **App Crawl**: given a single web app URL,
it launches a real browser, lets a human drive it through login and
bot-challenges, then autonomously clicks through the app while capturing every
API call it triggers. The results are exported as an OpenAPI spec and a Postman
collection.

---

## Quick start

```bash
./run.sh
```

That's it for day-to-day use — see [Running the app](#running-the-app) for
what this does and what to do if something's not already installed.

Open **http://localhost:5173** once it prints that the servers are up. With
`--prod`, open the single port it prints instead (see [Production mode](#production-mode---prod)).

---

## Table of contents

- [Architecture](#architecture)
- [Running the app](#running-the-app)
  - [One command: run.sh](#one-command-runsh)
  - [Running each piece manually](#running-each-piece-manually)
  - [Running locally and on a server](#running-locally-and-on-a-server)
- [Features](#features)
  - [App Crawl](#app-crawl)
  - [Exports](#exports)
- [How the remote browser works](#how-the-remote-browser-works)
- [Project layout](#project-layout)
- [Backend API reference](#backend-api-reference)
- [Configuration](#configuration)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Frontend  (React + TypeScript, Vite)  —  one origin for UI and /api │
│                                                                      │
│   App Crawl panel                    Settings                        │
│   - noVNC viewer (iframe, loaded     - Intercepting-proxy CA upload  │
│     through the backend's /vnc proxy)  and setup guide               │
│   - live capture review panel                                        │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ REST + WebSocket, same origin (/api)
┌───────────────────────────┴──────────────────────────────────────────┐
│  Backend  (FastAPI, Python)  —  serves /api, and the built UI in --prod │
│                                                                      │
│  crawl/                              export/                         │
│   - session.py    (Playwright, CDP)    - normalize.py (dedupe/template)│
│   - container.py  (Docker lifecycle)   - openapi.py   (OpenAPI 3.0.3)│
│   - walker.py     (autonomous crawl)   - postman.py   (Postman v2.1) │
│   - vnc_proxy.py  (noVNC relay)                                      │
│   - capture_poller.py, js_scan.py                                    │
│                                                                      │
│  core/   models.py, config.py, sessions_store.py (saved sessions)    │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ docker run (one container per crawl session)
┌───────────────────────────┴────────────────────────────────────────┐
│  vnc-browser image (Docker)                                          │
│                                                                        │
│   Xvfb (virtual display) ── fluxbox (borderless, single window)      │
│        │                                                              │
│        ├── Chromium (Playwright-bundled), --proxy-server=:9224       │
│        │        │                    CDP on 127.0.0.1:9222           │
│        │        │                                                     │
│        │        └── nginx reverse proxy :9223 → rewrites Host header │
│        │            + webSocketDebuggerUrl so CDP is reachable from  │
│        │            outside the container (Chrome only trusts        │
│        │            loopback-looking requests)                       │
│        │                                                              │
│        ├── mitmproxy :9224 — actual API-capture point (see below) — │
│        │        capture API on :9225, polled by the backend          │
│        │        └── [optional] forwards to an intercepting proxy     │
│        │            (e.g. Burp Suite) if configured at launch        │
│        │                                                              │
│        └── x11vnc (VNC server) ── websockify + noVNC ── :6080        │
│             (loopback only; the viewer iframe reaches it through     │
│              the backend's /api/crawl/{id}/vnc proxy)                 │
└──────────────────────────────────────────────────────────────────────┘
```

**Why a real browser in a container, streamed via VNC?** Many apps require a
login step, and login flows are often deliberately hostile to automation
(CAPTCHAs, bot-detection, MFA). Rather than trying to script around that,
ApiDiscover gives you the *actual* browser to drive by hand for that part —
over a real VNC connection, so mouse/keyboard input is genuine X11 input. Once you're past login, you hand control to the autonomous crawler, which drives the exact same browser/session/cookies via the Chrome DevTools Protocol (CDP). If the crawler gets stuck (a multi-step form, an unexpected page), it pauses and hands control back to you — the same VNC session, no separate mode.


**Why Docker per session?** Each crawl session gets its own disposable
container (Xvfb + Chromium + noVNC + a small nginx proxy). This keeps sessions
isolated from each other and from your host machine, and cleans up completely
when a session stops (`--rm`).

## Running the app

### One command: run.sh

```bash
./run.sh                                # start everything on defaults (backend 8000, frontend 5173, localhost)
./run.sh --rebuild                      # also rebuild the vnc-browser Docker image
./run.sh --backend-port 9000            # run the backend on a custom port
./run.sh --frontend-port 3000           # run the frontend on a custom port
./run.sh --expose                       # bind the frontend to 0.0.0.0 (reachable from other machines)
./run.sh --expose --frontend-port 3000  # expose the frontend on a custom port
./run.sh --prod --expose --frontend-port 8080  # production: one process, one port
```

Ports and bind address can also be set via env vars (`BACKEND_PORT`,
`FRONTEND_PORT`, `HOST=0.0.0.0`), which the flags above override.

What it does, in order:

1. Checks Docker is actually running (not just installed) — fails fast with a
   clear message if not.
2. Builds the `apidiscover-vnc-browser` image if it doesn't exist yet (skip
   with no flag if it's already built; force a rebuild with `--rebuild`).
3. Creates the backend virtualenv (`backend/.venv`) and installs
   `requirements.txt` if not already done.
4. Runs `npm install` for the frontend if `node_modules` doesn't exist yet.
5. Starts the backend (`uvicorn`, port 8000 by default) and frontend (`vite`,
   port 5173 by default) in the background, logging to
   `.run-logs/backend.log` and `.run-logs/frontend.log`. In dev mode the backend
   always binds to `127.0.0.1` — it's never reachable from outside the machine,
   even with `--expose`. The browser only ever talks to the frontend's own origin;
   Vite proxies `/api` (see `frontend/vite.config.ts`) through to the backend
   over `localhost` on the server side, so a custom `--backend-port` works
   without exposing that port publicly. By default the frontend binds to
   `localhost` only; `--expose` binds it to `0.0.0.0` so other machines on
   your network (or the internet, if the port is open) can reach it.
6. Prints the URLs and waits. **Ctrl+C** stops both processes and stops any
   crawl-session Docker containers left running (`apidiscover-crawl-*`).

#### Production mode (`--prod`)

Builds the frontend (`npm run build` into
`frontend/dist`) and starts a single uvicorn process on the frontend port (no
Vite, no `--reload`). That one process serves the built UI and `/api`, so only that one port needs to be open. Unknown paths fall back to `index.html` for client-side routing; `/api/*` paths never do.

Requirements: Docker Desktop (or another Docker daemon), Python 3.10+,
Node.js 18+.

### Running each piece manually

Useful for seeing live logs directly, or when you only need one piece.

**Backend:**
```bash
cd backend
python3 -m venv .venv          # first time only
source .venv/bin/activate
pip install -r requirements.txt   # first time only
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install    # first time only
npm run dev    # serves on http://localhost:5173
```
OR
```bash
npm run dev -- --host 0.0.0.0
```

**Production build, served by the backend (one port):**
```bash
cd frontend && npm run build                       # writes frontend/dist
cd ../backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080    # UI and /api both on :8080
```

**VNC browser image** (built once, reused by every crawl session — the
backend runs `docker run` against it per session, you don't run it directly
in normal use):
```bash
cd vnc-browser
docker build -t apidiscover-vnc-browser .
```

To manually sanity-check the image outside the app:
```bash
docker run -d --rm --name manual-test \
  -e CDP_HOST_PORT=7000 \
  -p 127.0.0.1:6080:6080 -p 127.0.0.1:7000:9223 \
  apidiscover-vnc-browser

curl -s http://localhost:7000/json/version   # should return Chrome version JSON
# open http://localhost:6080/vnc.html?autoconnect=true in a browser to see the desktop

docker stop manual-test
```

**Local test fixture** (a tiny 2-page app with fake API calls, for testing the
crawler against something you fully control instead of a live site):
```bash
cd backend
source .venv/bin/activate
uvicorn test_fixture.server:app --port 8100
# then Launch browser against http://localhost:8100/index.html in the app
```

## Running locally and on a server

ApiDiscover runs in one of two modes, and each works on your laptop or on a
server:

| | Dev (`./run.sh`) | Prod (`./run.sh --prod`) |
|---|---|---|
| Frontend | Vite dev server, hot reload | Built once with `npm run build`, served by the backend |
| Backend | `uvicorn --reload`, port 8000, loopback only | `uvicorn`, no reload, on the frontend's port |
| Ports open to the network | 1 (the frontend, with `--expose`) | 1 (the frontend port, with `--expose`) |
| Use it for | Developing the app | Running it for real, including on a server |

Both modes use the same origin for the page and `/api`, so the app behaves the
same way in each. Dev proxies `/api` through Vite. Prod serves `/api` and the
UI from one process.

### Prerequisites

| | Local (macOS/Linux/Windows with WSL) | Server (Linux) |
|---|---|---|
| Docker | Docker Desktop 4.x or newer, running | Docker Engine 20.10 or newer; the user must be in the `docker` group |
| Python | 3.10+ | 3.10+ (`python3-venv` on Debian/Ubuntu) |
| Node.js | 18+ | 18+ |
| Browser | not needed (crawl browsers run in Docker) | not needed |

`run.sh` creates the backend virtualenv and installs Python and npm dependencies
the first time it runs.

### Run it locally

```bash
git clone <repo> ApiDiscover && cd ApiDiscover

# Dev: hot reload, open http://localhost:5173
./run.sh

# Prod: built UI on one port, open http://localhost:8080
./run.sh --prod --frontend-port 8080
```

Press **Ctrl+C** to stop. `run.sh` stops the servers and any leftover crawl
containers.

Logs are in `.run-logs/backend.log` and `.run-logs/frontend.log`. `frontend.log`
is only written in dev mode.

### Run it on a server

The app has **no login**, and saved crawl sessions hold cookies and login
state (see [Configuration](#configuration)). Treat the server like a
private tool, and pick one of the options below. Don't open the port to the
whole internet.

**Option A: SSH tunnel (recommended).** Nothing is exposed. The server runs in
prod on localhost, and you reach it through an SSH tunnel.

```bash
# On the server
./run.sh --prod --frontend-port 8080           # listens on 127.0.0.1:8080 only

# On your laptop
ssh -N -L 8080:localhost:8080 user@your-server # leave this running
# then open http://localhost:8080 on your laptop
```

**Option B: open the port to your IP only.** Run it on all interfaces and
restrict access in the cloud firewall (AWS security group, GCP firewall rule,
or `ufw`) to your own IP address.

```bash
./run.sh --prod --expose --frontend-port 8080  # listens on 0.0.0.0:8080
# then open http://<server-ip>:8080
```

Allow inbound TCP on that port from your address only.

**Option C: public HTTPS behind a reverse proxy.** Use this only if the app
must be reachable from the internet. It needs a login layer, because the app
has none. Run the app on loopback (`./run.sh --prod --frontend-port 8080`) and
put nginx or Caddy in front with TLS and authentication. WebSockets need the
upgrade headers:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

**Keeping it running after you disconnect.** `run.sh` runs in the foreground.
Use `tmux` or `screen`:

```bash
tmux new -s apidiscover
./run.sh --prod --expose --frontend-port 8080
# detach with Ctrl+B then D; reattach later with: tmux attach -t apidiscover
```

### Checking that it works

```bash
curl -s http://localhost:8080/api/health       # {"status":"ok"}
```

Then open the UI and check that **Settings** loads (it shows the proxy CA
certificate status).
Start an App Crawl and confirm the browser viewer connects. You should see
`Connected` in the viewer.

From another machine, `curl` to the server's address should work only on the
port you opened and only from the address you allowed.

### Updating

```bash
git pull
./run.sh --prod --expose --frontend-port 8080   # rebuilds the frontend every time
```

- `run.sh` only installs Python dependencies when `fastapi` is missing. After
  changing `backend/requirements.txt`, run
  `backend/.venv/bin/pip install -r backend/requirements.txt` yourself.
- After changing anything under `vnc-browser/`, rebuild the browser image with
  `./run.sh --rebuild`.

### Settings that matter in each mode

| What | Dev | Prod |
|---|---|---|
| Frontend port | `--frontend-port` (default 5173) | `--frontend-port` (default 5173) |
| Backend port | `--backend-port` (default 8000), loopback only | not used; the backend shares the frontend port |
| Reachable from other machines | with `--expose` | with `--expose` |
| Hot reload | yes | no; rebuild or restart to see changes |

Env vars work too: `FRONTEND_PORT`, `BACKEND_PORT`, and `HOST=0.0.0.0`
(same as `--expose`).

## Features

### App Crawl

1. Enter a target URL, click **Launch browser** — a real Chromium instance
   starts in a fresh Docker container, streamed into the page via an embedded
   noVNC viewer. Tick **Save this session for later** first if you want to
   come back to it after stopping.
2. Interact with it directly (it's a real VNC session — mouse, keyboard,
   clipboard) to log in or get past anything automation-hostile.
3. Click **Start autonomous crawl** — control switches to a deterministic
   crawler that walks the DOM (clicking links/buttons/interactive elements,
   breadth/depth-limited, with cycle detection), still on the exact same
   browser/cookies/session.
4. If the crawler can't find a safe next action (stuck on a repeated page
   state, a form it can't fill, an unexpected error page), it pauses and the
   viewer hands control back to you — click through the sticking point
   manually, then **Resume autonomous crawl**. This loop can repeat as many
   times as needed.
5. Click **View captured APIs** at any time (crawling continues in the
   background) to see everything captured so far, deduplicated and
   normalized.
6. From that view:
   - **Exclude** a specific endpoint (method + host + path) — removes it from
     the current results and stops recording further matching calls for the
     rest of the session.
   - **Exclude all of `<host>`** — same, but for an entire base URL at once
     (useful for filtering out third-party trackers/ads/analytics domains
     picked up incidentally during the crawl).
   - **Scan JS files for endpoints** — actively fetches and scans JavaScript
     (including webpack chunks referenced from already-loaded bundles, not
     just scripts loaded during this specific crawl) for API-path-looking
     string literals, then attempts a live request through the same
     authenticated browser session to confirm each candidate actually exists
     before adding it to the results. These show up tagged
     `js_scan_verified` rather than `observed`, so you can tell "the crawler
     actually called this" apart from "this was found and confirmed by static
     analysis." An endpoint already seen live during crawling keeps its
     `observed` tag — JS-scan discovery never downgrades it.
   - Toggle **group by host** for the Postman export (see below).
   - **Export** — downloads both files immediately; exporting does not stop
     the crawl.
7. **Stop crawl** (separate, explicit action) tears down the browser
   container.

Exclusions are **session-scoped** by default: a normal session starts fresh
every time.

**Saved sessions.** A session started with **Save this session for later**
keeps its browser profile (cookies, login state), its captured requests, and
its exclusions on disk. It then appears under **Saved sessions**. **Resume**
relaunches the browser with that profile and history restored, and **Delete**
removes it. A session that is currently running can't be resumed or deleted;
stop it first.

There's no LLM in the loop anywhere in the crawler — "stuck" always means
"pause and ask a human," which is simpler, free, and more predictable than a
model guessing at a next action.


**Routing through an intercepting proxy (e.g. Burp Suite).** Before clicking
Launch browser, optionally check "Route this session's browser traffic
through an intercepting proxy" and enter its address (`host:port`) — a
"Check reachability" button verifies that address is actually reachable
before you commit to it. This is decided once, at launch: Chrome reads its
proxy setting a single time at process start, so it can't be changed
mid-session — to point a session at a different proxy, stop the crawl and
launch a new one. If you want HTTPS pages to load without certificate
warnings while proxying, upload the proxy's CA certificate on the Settings
page first (see [Configuration](#configuration)) — the Settings page also
has a step-by-step guide for same-machine, remote-backend, and
remote-Burp-server setups.

### Exports

Two files, generated from the same deduplicated/normalized endpoint list:

- **OpenAPI 3.0.3** (`discovered-api.openapi.json`) — one `servers` entry per
  discovered host; when a path is unique to one host it uses a clean,
  unprefixed path with a per-operation `servers` override (spec-correct way
  to say "this operation lives on a different host than the doc's default").
  Only in the rare case of the exact same path *and* method existing on two
  different hosts does the path get host-prefixed, since OpenAPI can't
  otherwise disambiguate two operations at the same path key.
- **Postman Collection v2.1** (`discovered-api.postman_collection.json`) —
  every request URL is fully-qualified (`https://actual-host.com/...`), no
  collection variables — avoids a class of bug where a shared `{{baseUrl}}`
  variable gets combined with an already-fully-qualified path, producing a
  broken doubled-up URL. Optionally grouped into one folder per host.

Path templating replaces numeric and UUID path segments with named
placeholders (`/users/482` → `/users/{id1}`) so repeated calls with different
IDs collapse into one documented endpoint instead of hundreds.

## How the remote browser works

This part had several non-obvious failure modes worth documenting for future
maintenance:

- **noVNC is reached through the backend, not directly.** Each session's
  container publishes its noVNC, CDP, and capture ports on `127.0.0.1` only.
  The viewer iframe loads `/api/crawl/{id}/vnc/vnc.html` from the same origin,
  and the backend relays both the HTML/assets and the WebSocket to the
  container ([backend/app/crawl/vnc_proxy.py](backend/app/crawl/vnc_proxy.py)).
  That's why a single exposed port is enough.
- **Chrome's CDP HTTP server only trusts loopback-looking `Host` headers.**
  A request arriving through Docker's published port carries
  `Host: localhost:<port>`, which Chrome resets as a DNS-rebinding
  protection — it doesn't matter that the traffic is actually local. The fix
  is an nginx reverse proxy *inside* the container
  ([cdp-proxy.conf.template](vnc-browser/cdp-proxy.conf.template)) that
  rewrites the `Host` header to `127.0.0.1:9222` before forwarding to Chrome.
- **Chrome's `/json/version` response embeds its own bind address** in
  `webSocketDebuggerUrl` (e.g. `ws://127.0.0.1:9222/...`). Playwright connects
  directly to whatever URL is in that field, bypassing the proxy entirely
  unless the response body is *also* rewritten. The same nginx config uses
  `sub_filter` to rewrite that embedded port to the real, dynamically-chosen
  host-published port.
- **That published port is only known once Docker picks it**, and is
  different for every concurrent session — so it can't be baked into the
  image. `start-nginx.sh` renders `cdp-proxy.conf` from the template at
  *container* startup using `envsubst`, substituting the `CDP_HOST_PORT`
  environment variable the backend passes in via `docker run -e`.
- **Port-allocation race:** two sessions starting near-simultaneously could
  otherwise be handed the same "free" port by the OS before either actually
  binds it. `container.py` holds the probe sockets open until right before
  `docker run` executes (shrinking the window) and serializes allocation
  with an `asyncio.Lock`, retrying with fresh ports if Docker still reports
  a bind conflict.
- **fluxbox (the window manager) draws its own decorations by default** —
  a title bar and a taskbar strip that visually eats into the remote
  display and adds a restore/minimize control that has no reason to exist
  (there's only ever one window). `fluxbox-apps` forces Chromium's window
  borderless and pinned to fill the entire virtual display; `fluxbox-init`
  disables the taskbar.
- **Corporate/VPN networks may block plain HTTP (port 80)** to the Ubuntu
  package mirrors while allowing HTTPS through — the Dockerfile rewrites
  `apt`'s sources to `https://` before installing anything, so `apt-get
  update` doesn't hang indefinitely on a blocked port.

## Project layout

```
ApiDiscover/
├── run.sh                    one-command dev/prod runner
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app entrypoint (CORS, routers, static UI)
│   │   ├── frontend_static.py serves frontend/dist in --prod (SPA fallback)
│   │   ├── api/               routes_crawl.py, routes_settings.py
│   │   ├── crawl/             session.py, container.py, walker.py,
│   │   │                      capture_poller.py (polls mitmproxy's capture API),
│   │   │                      vnc_proxy.py (relays noVNC HTTP + WebSocket),
│   │   │                      js_scan.py (JS endpoint discovery)
│   │   ├── export/            normalize.py, openapi.py, postman.py
│   │   └── core/              models.py, config.py,
│   │                          sessions_store.py (saved crawl sessions)
│   ├── tests/                 pytest suite (see Tests)
│   ├── test_fixture/          tiny local app for testing the crawler
│   ├── smoke_test.py          standalone crawl-pipeline smoke test
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx            top-level nav (Home / Settings)
│   │   ├── components/        AppCrawlPanel, BrowserViewer,
│   │   │                      CapturedEndpointsPanel, SettingsPanel
│   │   └── lib/
│   │       ├── api.ts         typed fetch/WebSocket client
│   │       └── api.test.ts    vitest tests for api.ts
│   └── vitest.config.ts
└── vnc-browser/               Docker image: Xvfb + Chromium + mitmproxy + noVNC + nginx
    ├── Dockerfile
    ├── supervisord.conf       process manager for everything in the container
    ├── start-browser.sh       waits for Xvfb + mitmproxy, launches Chromium
    ├── start-mitm.sh          starts mitmproxy, the actual API-capture point
    ├── capture_addon.py       mitmproxy addon: logs every request/response,
    │                          serves them over a small HTTP API
    ├── start-nginx.sh         renders cdp-proxy.conf from template, starts nginx
    ├── cdp-proxy.conf.template
    ├── fluxbox-apps           borderless/maximized window rule
    └── fluxbox-init           disables the taskbar
```

## Backend API reference

Everything lives under `/api`. The browser reaches it through the frontend's
origin. In dev mode the backend listens on `http://localhost:8000` on the
server; in `--prod` it's the same port as the UI. Interactive docs (Swagger UI)
are at `/docs` on the backend's port.

**General**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |

**Settings** (`/api/settings`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/proxy-ca-cert` | Whether an intercepting-proxy CA certificate is configured |
| PUT | `/proxy-ca-cert` | Upload a PEM CA certificate (multipart `file`); must start with `-----BEGIN CERTIFICATE-----` |
| DELETE | `/proxy-ca-cert` | Remove the configured CA certificate |

**Crawl** (`/api/crawl`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/static-extension-groups` | Preset extension groups for the "exclude static files" toggle |
| POST | `/proxy/check` | Check that a `host:port` proxy is reachable from inside a container |
| POST | `/start` | Launch a crawl session (body: `start_url`, optional `proxy_server`, `save_session`). Returns `session_id` and `novnc_url`, a same-origin path |
| GET | `/sessions` | List saved sessions, with `active` and `endpoint_count` |
| POST | `/sessions/{id}/resume` | Relaunch a saved session with its profile and history restored (optional body: `proxy_server`) |
| DELETE | `/sessions/{id}` | Delete a saved session (refused while it's active) |
| GET | `/{id}/endpoints` | Current normalized, exclusion-filtered endpoint list — safe to poll anytime |
| GET | `/{id}/exclusions` | Current host, endpoint, extension, and method exclusions |
| POST | `/{id}/exclude-host`, `/{id}/include-host` | Exclude or re-include an entire host |
| POST | `/{id}/exclude-endpoint`, `/{id}/include-endpoint` | Exclude or re-include one (method, host, path_template) |
| POST | `/{id}/exclude-extension`, `/{id}/include-extension` | Exclude or re-include a file extension |
| POST | `/{id}/exclude-method`, `/{id}/include-method` | Exclude or re-include an HTTP method |
| POST | `/{id}/scan-js` | Actively fetch + scan JS for API paths, then live-verify candidates through the session's browser |
| POST | `/{id}/upload` | Upload a file into the session browser's Uploads folder (multipart `file`) |
| GET | `/{id}/export?group_by_host=` | Returns `{openapi, postman, endpoint_count}` |
| POST | `/{id}/stop` | Stops the crawl and tears down its container |
| GET, HEAD | `/{id}/vnc/{path}` | noVNC's HTML and assets, relayed from the session's container (not in OpenAPI) |
| WS | `/{id}/vnc/{path}` | noVNC's RFB stream, relayed from the session's container |
| WS | `/{id}/stream` | Live `capture`/`status`/`js_scan_done`/`js_scan_error` events out; `start_autonomous` / `resume_autonomous` / `stop_autonomous` control messages in |

## Configuration

- **Intercepting-proxy CA certificate** — uploaded via the Settings page,
  stored as a plain PEM file at `backend/data/proxy_ca.pem` (gitignored; not
  encrypted, since a CA certificate is a public document with no private key
  involved — there's nothing at rest here that needs protecting). Bind-mounted
  read-only into a session's container and consumed by mitmproxy
  ([vnc-browser/start-mitm.sh](vnc-browser/start-mitm.sh)) to validate its own
  outbound connection to the configured upstream proxy — Chrome itself never
  sees this cert; it only ever trusts mitmproxy's own CA
  (`~/.mitmproxy/mitmproxy-ca-cert.pem`, generated fresh per container),
  since mitmproxy is the only thing Chrome talks to directly now.
- **Saved App Crawl sessions** — stored under `backend/data/sessions/<id>/`
  (`session.json`, `captured.jsonl`, and the Chrome `profile/`). They aren't
  encrypted. The profile holds cookies and login state, so treat that
  directory as sensitive. Deleting a saved session removes its directory.
- **Ports** — backend defaults to `8000`, frontend to `5173`; both are
  configurable via `run.sh --backend-port` / `--frontend-port` (see
  [One command: run.sh](#one-command-runsh)). Each crawl session's noVNC, CDP,
  and capture ports are chosen by the OS and published on `127.0.0.1` only.
  The viewer reaches noVNC through the backend at
  `/api/crawl/{session_id}/vnc/...` ([backend/app/crawl/vnc_proxy.py](backend/app/crawl/vnc_proxy.py)),
  which relays both its HTML/assets and its WebSocket, so noVNC is never
  exposed directly.
- **Frontend → backend requests** — [frontend/src/lib/api.ts](frontend/src/lib/api.ts)
  fetches everything from the page's own origin (`/api/...`, no host or port
  of its own). [frontend/vite.config.ts](frontend/vite.config.ts) proxies
  `/api` (HTTP and the WebSocket upgrades under it) to
  `http://localhost:$BACKEND_PORT`, which `run.sh` passes through as the
  `BACKEND_PORT` env var. Since that proxying happens in Vite's own process on
  the server, "localhost" there correctly means the server itself — so the
  backend can stay bound to `127.0.0.1` and never needs to be reachable from
  outside the machine, even when the frontend is exposed with `--expose`. This
  also means the browser works unmodified whether you load the page via
  `localhost`, `127.0.0.1`, or a LAN/public IP — it never needs to know the
  backend's real address.

## Tests

Backend (pytest, from `backend/`):

```bash
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd backend && .venv/bin/python -m pytest
```

Covers: the noVNC HTTP and WebSocket relay (against a fake noVNC server), the
loopback-only container port bindings, the App Crawl routes (start, saved
sessions, resume, delete), saved-session storage and exclusion persistence,
Settings (proxy CA certificate upload and removal), the export
pipeline (normalize, OpenAPI, Postman), JS-scan helpers, the static frontend
serving and its path-traversal guard, and CORS.

Frontend (vitest, from `frontend/`):

```bash
cd frontend && npm test
```

Covers the WebSocket and fetch helpers in `src/lib/api.ts`.

Not covered by automated tests: the React components, the Playwright DOM
walker, `run.sh` itself, and anything that needs a live Docker container. Those
were checked by hand (the noVNC viewer was loaded in headless Chromium through
the proxy and connected).

## Troubleshooting

**"Docker doesn't seem to be running"** — start Docker Desktop, then re-run
`./run.sh`.

**`docker build` hangs or times out fetching packages** — if you're on a
corporate network/VPN, plain HTTP (port 80) to package mirrors may be
blocked. The Dockerfile already forces HTTPS mirrors for exactly this reason;
if you still see timeouts, check `curl -v http://ports.ubuntu.com` vs
`https://` to confirm which is blocked in your environment.

**`ECONNREFUSED` connecting to CDP, or the browser never appears** — almost
always means the vnc-browser image is stale relative to the backend/session
code. Rebuild with `./run.sh --rebuild`.

**Settings or App Crawl shows "Failed to fetch"** — the page can't
reach the backend through its own origin. Check that the server is running
(`.run-logs/backend.log`) and that you opened the frontend port `run.sh`
printed. The backend is deliberately not exposed on its own port, so
opening `:8000` from another machine won't work. For a remote server, run
`./run.sh --prod --expose --frontend-port <port>` and open that one port.

**The App Crawl viewer is blank or won't connect** — check that the session's
container is running (`docker ps --filter name=apidiscover-crawl-`) and that
the backend log has no errors. The viewer loads through the backend, so the
backend has to be up.

**Resume or delete of a saved session is refused (409)** — the session is
still running. Stop it first.

**Clicks/keyboard don't reach the remote browser** — the noVNC iframe should
accept input directly; if it doesn't seem to, click once inside the iframe
first to give it focus. Copy/paste into the remote browser depends on the
browser's own clipboard permissions for the noVNC page — not yet fully wired
up.

**Leftover `apidiscover-crawl-*` containers after a crash** —
```bash
docker ps -a --filter "name=apidiscover-crawl-"
docker stop $(docker ps -q --filter "name=apidiscover-crawl-")
```
`run.sh` does this automatically on a clean Ctrl+C, but not after a hard
crash of the backend process.

**Backend/frontend fail to start under `run.sh`** — check
`.run-logs/backend.log` / `.run-logs/frontend.log` for the actual error.
