# ApiDiscover

An API endpoint discovery tool built for an **external, attacker's-eye view** of your
attack surface — rather than relying solely on internal Postman collections
(which only document what someone already knew to write down), ApiDiscover
finds what's actually reachable from outside your network perimeter.

It has two complementary modes:

- **Domain Recon** — given a root domain, discover subdomains/hosts via passive
  OSINT, active DNS brute-force, and third-party attack-surface APIs (Shodan,
  Censys, SecurityTrails, VirusTotal, Wallarm).
- **App Crawl** — given a single web app URL, launch a real browser, let a human
  drive it through login/bot-challenges, then autonomously click through the
  app while capturing every API call it triggers — exported as an OpenAPI spec
  and a Postman collection.

The two modes chain together: a host discovered by Domain Recon can be sent
straight into App Crawl with one click.

---

## Quick start

```bash
./run.sh
```

That's it for day-to-day use — see [Running the app](#running-the-app) for
what this does and what to do if something's not already installed.

Open **http://localhost:5173** once it prints that the servers are up.

---

## Table of contents

- [Architecture](#architecture)
- [Running the app](#running-the-app)
  - [One command: run.sh](#one-command-runsh)
  - [Running each piece manually](#running-each-piece-manually)
- [Features](#features)
  - [Domain Recon](#domain-recon)
  - [App Crawl](#app-crawl)
  - [Exports](#exports)
- [How the remote browser works](#how-the-remote-browser-works)
- [Project layout](#project-layout)
- [Backend API reference](#backend-api-reference)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Frontend  (React + TypeScript, Vite)  —  http://localhost:5173      │
│                                                                        │
│   Home                                    Settings                    │
│   ┌─────────────┐  ┌─────────────────┐   ┌──────────────────────┐    │
│   │ Recon Panel │  │ App Crawl Panel │   │ Recon provider config │    │
│   │             │  │  - noVNC iframe │   │ (Shodan/Censys/...)   │    │
│   │             │  │  - live capture │   └──────────────────────┘    │
│   │             │  │    review panel │                               │
│   └─────────────┘  └─────────────────┘                               │
└───────────────────────────┬────────────────────────────────────────┘
                             │ REST + WebSocket
┌───────────────────────────┴────────────────────────────────────────┐
│  Backend  (FastAPI, Python)  —  http://localhost:8000               │
│                                                                        │
│  recon/                          crawl/                              │
│   - passive.py   (crt.sh)         - session.py  (Playwright, CDP)    │
│   - active.py    (DNS bruteforce) - container.py (Docker lifecycle)  │
│   - third_party.py (Shodan, etc)  - walker.py   (autonomous crawler) │
│   - wallarm.py   (paginated POST)                                    │
│   - orchestrator.py (fan-out + liveness probe)                       │
│                                                                        │
│  export/                          core/                              │
│   - normalize.py (dedupe/template)  - models.py  (shared schemas)    │
│   - openapi.py   (OpenAPI 3.0.3)    - config.py  (encrypted secrets) │
│   - postman.py   (Postman v2.1)                                      │
└───────────────────────────┬────────────────────────────────────────┘
                             │ docker run (one container per crawl session)
┌───────────────────────────┴────────────────────────────────────────┐
│  vnc-browser image (Docker)                                          │
│                                                                        │
│   Xvfb (virtual display) ── fluxbox (borderless, single window)      │
│        │                                                              │
│        ├── Chromium (Playwright-bundled) ── CDP on 127.0.0.1:9222    │
│        │        │                                                     │
│        │        └── nginx reverse proxy :9223 → rewrites Host header │
│        │            + webSocketDebuggerUrl so CDP is reachable from  │
│        │            outside the container (Chrome only trusts        │
│        │            loopback-looking requests)                       │
│        │                                                              │
│        └── x11vnc (VNC server) ── websockify + noVNC ── :6080        │
│             (embedded directly in the frontend via an iframe)        │
└──────────────────────────────────────────────────────────────────────┘
```

**Why a real browser in a container, streamed via VNC?** Many apps require a
login step, and login flows are often deliberately hostile to automation
(CAPTCHAs, bot-detection, MFA). Rather than trying to script around that,
ApiDiscover gives you the *actual* browser to drive by hand for that part —
over a real VNC connection, so mouse/keyboard input is genuine X11 input, not
forwarded through a fragile CDP input-injection layer. Once you're past login,
you hand control to the autonomous crawler, which drives the exact same
browser/session/cookies via the Chrome DevTools Protocol (CDP). If the crawler
gets stuck (a multi-step form, an unexpected page), it pauses and hands
control back to you — the same VNC session, no separate mode.

**Why Docker per session?** Each crawl session gets its own disposable
container (Xvfb + Chromium + noVNC + a small nginx proxy). This keeps sessions
isolated from each other and from your host machine, and cleans up completely
when a session stops (`--rm`).

## Running the app

### One command: run.sh

```bash
./run.sh              # start everything
./run.sh --rebuild    # also rebuild the vnc-browser Docker image
```

What it does, in order:

1. Checks Docker is actually running (not just installed) — fails fast with a
   clear message if not.
2. Builds the `apidiscover-vnc-browser` image if it doesn't exist yet (skip
   with no flag if it's already built; force a rebuild with `--rebuild` after
   changing anything under `vnc-browser/`).
3. Creates the backend virtualenv (`backend/.venv`) and installs
   `requirements.txt` if not already done.
4. Runs `npm install` for the frontend if `node_modules` doesn't exist yet.
5. Starts the backend (`uvicorn`, port 8000) and frontend (`vite`, port 5173)
   in the background, logging to `.run-logs/backend.log` and
   `.run-logs/frontend.log`.
6. Prints the URLs and waits. **Ctrl+C** stops both processes and stops any
   crawl-session Docker containers left running (`apidiscover-crawl-*`).

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
  -p 6080:6080 -p 7000:9223 \
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

## Features

### Domain Recon

Given a root domain, runs multiple discovery sources concurrently and merges
the results into a deduplicated host list with basic liveness info (HTTP
status, page title, `Server` header):

| Source | Type | Notes |
|---|---|---|
| Certificate transparency (crt.sh) | Passive | No API key, no traffic to the target |
| DNS brute-force | Active | Wordlist-based, generates real DNS queries against the target |
| Shodan | Third-party API | Requires API key |
| Censys | Third-party API | Requires API key |
| SecurityTrails | Third-party API | Requires API key |
| VirusTotal | Third-party API | Requires API key |
| Wallarm | Third-party API | Requires token + client ID + `wsess` cookie; paginated |

Provider credentials are configured once in the **Settings** page and stored
encrypted at rest (`backend/data/provider_config.enc`, key in
`backend/data/secret.key` — both gitignored). Disabled or unconfigured
providers are silently skipped, not treated as errors.

Each discovered, reachable host has a **"Send to App Crawl"** button that
pre-fills the App Crawl target — the two modes are meant to be used together.

**Adding a new recon provider:** the provider interface is intentionally
pluggable —

- `ApiListProvider` ([backend/app/recon/base.py](backend/app/recon/base.py))
  for a simple single GET request with header/query auth (see
  [third_party.py](backend/app/recon/third_party.py) for Shodan/Censys/etc.
  as examples).
- `PaginatedApiProvider` (same file) for POST + JSON body + cookie auth +
  offset/limit pagination (see
  [wallarm.py](backend/app/recon/wallarm.py)).

A new provider is a small subclass plus one line registering it in
`default_providers()` in
[orchestrator.py](backend/app/recon/orchestrator.py) — no changes to the
orchestration logic itself.

### App Crawl

1. Enter a target URL, click **Launch browser** — a real Chromium instance
   starts in a fresh Docker container, streamed into the page via an embedded
   noVNC viewer.
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
   - Toggle **group by host** for the Postman export (see below).
   - **Export** — downloads both files immediately; exporting does not stop
     the crawl.
7. **Stop crawl** (separate, explicit action) tears down the browser
   container.

Exclusions are **session-scoped** — they reset on the next crawl, they don't
persist across runs.

There's no LLM in the loop anywhere in the crawler — "stuck" always means
"pause and ask a human," which is simpler, free, and more predictable than a
model guessing at a next action.

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
├── run.sh                    one-command dev runner
├── backend/
│   ├── app/
│   │   ├── main.py           FastAPI app entrypoint
│   │   ├── api/               routes_recon.py, routes_crawl.py
│   │   ├── recon/              provider interfaces + implementations
│   │   ├── crawl/               session.py, container.py, walker.py
│   │   ├── export/              normalize.py, openapi.py, postman.py
│   │   └── core/                 models.py, config.py
│   ├── test_fixture/          tiny local app for testing the crawler
│   ├── smoke_test.py          standalone crawl-pipeline smoke test
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx            top-level nav (Home / Settings)
│       ├── components/         ReconPanel, AppCrawlPanel, BrowserViewer,
│       │                       CapturedEndpointsPanel, SettingsPanel
│       └── lib/api.ts          typed fetch/WebSocket client
└── vnc-browser/               Docker image: Xvfb + Chromium + noVNC + nginx
    ├── Dockerfile
    ├── supervisord.conf        process manager for everything in the container
    ├── start-browser.sh        waits for Xvfb, launches Chromium
    ├── start-nginx.sh          renders cdp-proxy.conf from template, starts nginx
    ├── cdp-proxy.conf.template
    ├── fluxbox-apps            borderless/maximized window rule
    └── fluxbox-init            disables the taskbar
```

## Backend API reference

All endpoints are under `http://localhost:8000`.

**Recon** (`/api/recon`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/providers` | List configured providers (secrets excluded) |
| PUT | `/providers` | Create/update a provider's config (api_key, cookies, extra) |
| POST | `/run` | Run recon against a domain, returns merged + liveness-probed hosts |

**Crawl** (`/api/crawl`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/start` | Launch a new crawl session (starts the VNC container), returns `session_id` + `novnc_url` |
| GET | `/{session_id}/endpoints` | Current normalized, exclusion-filtered endpoint list — safe to poll anytime |
| POST | `/{session_id}/exclude-host` | Exclude an entire host going forward |
| POST | `/{session_id}/exclude-endpoint` | Exclude one (method, host, path_template) |
| GET | `/{session_id}/export?group_by_host=` | Returns `{openapi, postman, endpoint_count}` |
| POST | `/{session_id}/stop` | Stops the crawl and tears down its container |
| WS | `/{session_id}/stream` | Live `capture`/`status` events out; `start_autonomous` / `resume_autonomous` / `stop_autonomous` control messages in |

Interactive docs (Swagger UI) are always available at
`http://localhost:8000/docs` while the backend is running.

## Configuration

- **Recon provider credentials** — set via the Settings page in the app, not
  environment variables. Stored encrypted at `backend/data/provider_config.enc`
  (Fernet key in `backend/data/secret.key`). Both are gitignored; deleting
  them resets all provider config.
- **Ports** — backend `8000`, frontend `5173`, noVNC and CDP ports per
  session are chosen dynamically by the OS and are not fixed.
- **Frontend → backend URL** — hardcoded to `http://localhost:8000` in
  [frontend/src/lib/api.ts](frontend/src/lib/api.ts); change there if running
  the backend on a different host/port.

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
