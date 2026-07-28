#!/bin/bash
# One-command dev runner for ApiDiscover: sets up (if needed) and starts the
# backend, frontend, and ensures the VNC browser Docker image exists.
#
# Usage:
#   ./run.sh            start everything
#   ./run.sh --rebuild   also rebuild the vnc-browser Docker image
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VNC_DIR="$ROOT_DIR/vnc-browser"
LOG_DIR="$ROOT_DIR/.run-logs"
VNC_IMAGE="apidiscover-vnc-browser"

REBUILD_IMAGE=false
if [[ "${1:-}" == "--rebuild" ]]; then
  REBUILD_IMAGE=true
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

# --- VNC browser image ---
if $REBUILD_IMAGE || ! docker image inspect "$VNC_IMAGE" >/dev/null 2>&1; then
  echo "Building $VNC_IMAGE image (this can take a couple of minutes the first time)..."
  docker build -t "$VNC_IMAGE" "$VNC_DIR"
else
  echo "[ok] $VNC_IMAGE image already exists (use --rebuild to force a rebuild)"
fi

# --- Backend setup ---
cd "$BACKEND_DIR"
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

# --- Start backend ---
cd "$BACKEND_DIR"
source .venv/bin/activate
echo "Starting backend on http://localhost:8000 ..."
uvicorn app.main:app --reload --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# --- Start frontend ---
cd "$FRONTEND_DIR"
echo "Starting frontend on http://localhost:5173 ..."
npm run dev -- --port 5173 > "$LOG_DIR/frontend.log" 2>&1 &
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
echo "   Frontend: http://localhost:5173"
echo "   Backend:  http://localhost:8000"
echo ""
echo " Logs: $LOG_DIR/backend.log, $LOG_DIR/frontend.log"
echo " Press Ctrl+C to stop everything."
echo "================================================"
echo ""

wait "$BACKEND_PID" "$FRONTEND_PID"
