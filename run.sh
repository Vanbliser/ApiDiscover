#!/bin/bash
# One-command dev runner for ApiDiscover: sets up (if needed) and starts the
# backend, frontend, and ensures the VNC browser Docker image exists.
#
# Usage:
#   ./run.sh                                start everything on defaults
#   ./run.sh --rebuild                      also rebuild the vnc-browser Docker image
#   ./run.sh --backend-port 9000            run the backend on a custom port
#   ./run.sh --frontend-port 3000           run the frontend on a custom port
#   ./run.sh --expose                       bind the frontend to 0.0.0.0 (reachable from other machines)
#   ./run.sh --expose --frontend-port 3000  expose the frontend on a custom port
#   ./run.sh --prod --expose --frontend-port 8080
#                                           production: build the frontend and serve the UI and
#                                           /api from ONE process on ONE port (no Vite, no --reload)
#
# Env vars (overridden by the flags above): BACKEND_PORT, FRONTEND_PORT, HOST
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VNC_DIR="$ROOT_DIR/vnc-browser"
LOG_DIR="$ROOT_DIR/.run-logs"
VNC_IMAGE="apidiscover-vnc-browser"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${HOST:-localhost}"
REBUILD_IMAGE=false
PROD=false

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild)
      REBUILD_IMAGE=true
      shift
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    --backend-port=*)
      BACKEND_PORT="${1#*=}"
      shift
      ;;
    --frontend-port)
      FRONTEND_PORT="$2"
      shift 2
      ;;
    --frontend-port=*)
      FRONTEND_PORT="${1#*=}"
      shift
      ;;
    --expose)
      FRONTEND_HOST="0.0.0.0"
      shift
      ;;
    --prod)
      PROD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! [[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || ! [[ "$FRONTEND_PORT" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ports must be numeric (got backend=$BACKEND_PORT frontend=$FRONTEND_PORT)" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Shutting down..."
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true

  # Stop any crawl-session containers left running from this app instance.
  local orphans
  orphans=$(docker ps -q --filter "name=apidiscover-crawl-" 2>/dev/null || true)
  if [[ -n "$orphans" ]]; then
    echo "Stopping leftover crawl session containers..."
    docker stop $orphans >/dev/null 2>&1 || true
  fi

  echo "Stopped."
}
trap cleanup EXIT INT TERM

echo "== ApiDiscover dev runner =="

# --- Docker daemon check ---
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker doesn't seem to be running. Start Docker Desktop and try again."
  exit 1
fi
echo "[ok] Docker is running"

# --- Docker Engine version (host-gateway needs 20.10+) ---
MIN_DOCKER_VERSION="20.10"
DOCKER_VERSION="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 0)"
LOWEST="$(printf '%s\n%s\n' "$MIN_DOCKER_VERSION" "$DOCKER_VERSION" | sort -V | head -1)"
if [[ "$LOWEST" != "$MIN_DOCKER_VERSION" ]]; then
  echo "ERROR: Docker Engine $DOCKER_VERSION is too old. ApiDiscover needs $MIN_DOCKER_VERSION or newer."
  echo "       Update Docker Desktop (macOS) or Docker Engine (Linux) and try again."
  exit 1
fi
echo "[ok] Docker Engine $DOCKER_VERSION (>= $MIN_DOCKER_VERSION)"

# --- VNC browser image ---
if $REBUILD_IMAGE || ! docker image inspect "$VNC_IMAGE" >/dev/null 2>&1; then
  echo "Building $VNC_IMAGE image (this can take a couple of minutes the first time)..."
  docker build -t "$VNC_IMAGE" "$VNC_DIR"
else
  echo "[ok] $VNC_IMAGE image already exists (use --rebuild to force a rebuild)"
fi

# --- Backend setup ---
cd "$BACKEND_DIR"
pwd
if [[ ! -d ".venv" ]]; then
  echo "Creating backend virtualenv..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if ! python -c "import fastapi" >/dev/null 2>&1; then
  echo "Installing backend dependencies..."
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
fi

if ! python -c "from playwright.sync_api import sync_playwright" >/dev/null 2>&1 || \
   [[ ! -d "$HOME/Library/Caches/ms-playwright" && ! -d "$HOME/.cache/ms-playwright" ]]; then
  echo "Installing Playwright's Chromium (used for --rebuild image sanity, not the crawl browser itself)..."
  playwright install chromium >/dev/null 2>&1 || true
fi

echo "[ok] Backend dependencies ready"

# --- Frontend setup ---
cd "$FRONTEND_DIR"
if [[ ! -d "node_modules" ]]; then
  echo "Installing frontend dependencies..."
  npm install --silent
fi
echo "[ok] Frontend dependencies ready"

# --- Production: one process serves the built UI and /api on FRONTEND_PORT ---
if $PROD; then
  echo "Building frontend for production..."
  if ! (cd "$FRONTEND_DIR" && npm run build) > "$LOG_DIR/frontend-build.log" 2>&1; then
    echo "ERROR: frontend build failed. Check $LOG_DIR/frontend-build.log"
    exit 1
  fi
  echo "[ok] Frontend built"

  cd "$BACKEND_DIR"
  source .venv/bin/activate
  echo "Starting ApiDiscover on http://$FRONTEND_HOST:$FRONTEND_PORT ..."
  if [[ "$FRONTEND_HOST" == "0.0.0.0" ]]; then
    echo "  (exposed: reachable from other machines on your network)"
  fi
  FRONTEND_PORT="$FRONTEND_PORT" uvicorn app.main:app --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!

  sleep 2
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: server failed to start. Check $LOG_DIR/backend.log"
    exit 1
  fi

  echo ""
  echo "================================================"
  echo " ApiDiscover is running (production):"
  echo "   http://$FRONTEND_HOST:$FRONTEND_PORT"
  echo ""
  echo " Logs: $LOG_DIR/backend.log"
  echo " Press Ctrl+C to stop."
  echo "================================================"
  echo ""

  wait "$BACKEND_PID"
  exit 0
fi

# --- Start backend ---
cd "$BACKEND_DIR"
source .venv/bin/activate
echo "Starting backend on http://localhost:$BACKEND_PORT ..."
FRONTEND_PORT="$FRONTEND_PORT" uvicorn app.main:app --reload --port "$BACKEND_PORT" > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# --- Start frontend ---
cd "$FRONTEND_DIR"
DISPLAY_HOST="$FRONTEND_HOST"
[[ "$DISPLAY_HOST" == "0.0.0.0" ]] && DISPLAY_HOST="localhost"
echo "Starting frontend on http://$FRONTEND_HOST:$FRONTEND_PORT ..."
if [[ "$FRONTEND_HOST" == "0.0.0.0" ]]; then
  echo "  (exposed: reachable from other machines on your network)"
fi
BACKEND_PORT="$BACKEND_PORT" npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

sleep 2

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "ERROR: backend failed to start. Check $LOG_DIR/backend.log"
  exit 1
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "ERROR: frontend failed to start. Check $LOG_DIR/frontend.log"
  exit 1
fi

echo ""
echo "================================================"
echo " ApiDiscover is running:"
echo "   Frontend: http://$DISPLAY_HOST:$FRONTEND_PORT"
echo "   Backend:  http://localhost:$BACKEND_PORT (loopback-only; the frontend"
echo "             proxies /api to it, see frontend/vite.config.ts)"
echo ""
echo " Logs: $LOG_DIR/backend.log, $LOG_DIR/frontend.log"
echo " Press Ctrl+C to stop everything."
echo "================================================"
echo ""

wait "$BACKEND_PID" "$FRONTEND_PID"
