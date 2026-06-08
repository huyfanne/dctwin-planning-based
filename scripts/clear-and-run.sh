#!/usr/bin/env bash
#
# clear-and-run.sh — wipe plan state, then start the Digital Twin web app.
#
# Default (single-origin): build the frontend and serve the WHOLE app from the
# backend at http://localhost:8000 (UI at /, API at /api/*). One URL, no proxy.
#
# Usage:
#   scripts/clear-and-run.sh [--dev] [--backend-only]
#                            [--keep-runs] [-y|--yes] [-h|--help]
#     --dev           hot-reload: backend + Vite dev server at http://localhost:5173
#     --backend-only  run only the API (no build); serves a built UI at / if present
#     --keep-runs     don't delete existing plans   -y/--yes  skip the delete prompt
#
# Env overrides: OPERATOR_TOKEN=op-secret EXPERT_TOKEN=ex-secret
#                BACKEND_PORT=8000 FRONTEND_PORT=5173  (a busy port auto-bumps to the next free one)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="$ROOT/src"
PY="$ROOT/.venv-dtwin/bin/python"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
OPERATOR_TOKEN="${OPERATOR_TOKEN:-op-secret}"
EXPERT_TOKEN="${EXPERT_TOKEN:-ex-secret}"

MODE=single; CLEAR_RUNS=1; ASSUME_YES=0; BACKEND_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --dev)           MODE=dev ;;
    --backend-only)  BACKEND_ONLY=1 ;;
    --keep-runs)     CLEAR_RUNS=0 ;;
    -y|--yes)        ASSUME_YES=1 ;;
    -h|--help)       sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown arg: $arg (try --help)" >&2; exit 2 ;;
  esac
done

port_listening() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }   # anything listening (even foreign-owned)

kill_port() {                          # kill OUR processes on the port; wait, then SIGKILL
  local port="$1" pids
  pids="$(lsof -ti:"$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]] && command -v fuser >/dev/null 2>&1; then
    pids="$(fuser "$port"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true)"
  fi
  [[ -n "$pids" ]] || return 0
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 6); do port_listening "$port" || return 0; sleep 0.5; done
  kill -9 $pids 2>/dev/null || true; sleep 0.5
}

resolve_port() {                       # echo a usable port: $1 if free, else the next free one (scan +1..+20)
  local want="$1" label="$2" p
  if ! port_listening "$want"; then echo "$want"; return 0; fi
  for ((p = want + 1; p <= want + 20; p++)); do
    port_listening "$p" && continue
    echo "  $label :$want is in use (held by another process — e.g. a Docker container);" \
         "falling back to :$p" >&2
    echo "$p"; return 0
  done
  echo "ERROR: no free $label port in $want-$((want + 20)). Free one (sg docker -c 'docker ps')" \
       "or pass an explicit BACKEND_PORT=/FRONTEND_PORT=." >&2
  exit 1
}

start_backend_bg() {   # backgrounded + logged (used by --dev)
  mkdir -p "$SRC/log"
  sg docker -c "cd '$SRC' && PYTHONPATH='$SRC' OPERATOR_TOKEN='$OPERATOR_TOKEN' EXPERT_TOKEN='$EXPERT_TOKEN' \
    '$PY' -m uvicorn webapp.main:app --host 0.0.0.0 --port $BACKEND_PORT" > "$SRC/log/backend.out" 2>&1 &
  for _ in $(seq 1 30); do port_listening "$BACKEND_PORT" && return 0; sleep 1; done
  echo "  (backend not up yet — see src/log/backend.out)"
}

run_backend_fg() {     # foreground (used by single / --backend-only); Ctrl-C stops it
  cd "$SRC"
  sg docker -c "PYTHONPATH='$SRC' OPERATOR_TOKEN='$OPERATOR_TOKEN' EXPERT_TOKEN='$EXPERT_TOKEN' \
    '$PY' -m uvicorn webapp.main:app --host 0.0.0.0 --port $BACKEND_PORT"
}

build_frontend() {
  command -v npm >/dev/null || { echo "npm not found" >&2; exit 1; }
  [[ -d "$SRC/frontend/node_modules" ]] || ( cd "$SRC/frontend" && npm install )
  echo "• building frontend → dist/"
  ( cd "$SRC/frontend" && npm run build >/dev/null )
}

# 1. Stop our own stale servers, then resolve the ports we need — auto-bumping to the
#    next free port if the requested one is held by something we can't kill (e.g. a
#    Docker container). Resolved BEFORE clearing/building, so nothing is wasted.
echo "• stopping servers on :$BACKEND_PORT and :$FRONTEND_PORT"
kill_port "$BACKEND_PORT"; kill_port "$FRONTEND_PORT"
BACKEND_PORT="$(resolve_port "$BACKEND_PORT" backend)"
[[ "$MODE" == dev ]] && FRONTEND_PORT="$(resolve_port "$FRONTEND_PORT" frontend)"

# 2. Clear state (runs/ + index.db are recreated on the next plan).
if [[ "$CLEAR_RUNS" == 1 && "$ASSUME_YES" != 1 ]]; then
  read -r -p "Delete ALL plans in $SRC/runs (irreversible)? [y/N] " ans || ans=""
  [[ "$ans" =~ ^[Yy]$ ]] || { CLEAR_RUNS=0; echo "  keeping runs/"; }
fi
if [[ "$CLEAR_RUNS" == 1 ]]; then
  rm -rf "$SRC/runs"; echo "• cleared runs/ (plans + index.db)"
  rm -f "$SRC"/log/* 2>/dev/null || true
fi
rm -rf "$SRC/frontend/.vite" 2>/dev/null || true

# Tear both down on exit (incl. Ctrl-C from the foreground process).
cleanup() { echo; echo "• stopping…"; kill_port "$BACKEND_PORT"; kill_port "$FRONTEND_PORT"; }
trap cleanup EXIT INT TERM

[[ -x "$PY" ]] || { echo "interpreter not found: $PY" >&2; exit 1; }

# 3. Backend-only — just the API (serves a built UI at / if one exists).
if [[ "$BACKEND_ONLY" == 1 ]]; then
  echo; echo "  API/UI:  http://localhost:$BACKEND_PORT   (UI served at / only if already built)"
  echo "  Token:   operator=$OPERATOR_TOKEN  expert=$EXPERT_TOKEN"; echo
  echo "• starting backend on :$BACKEND_PORT  (Ctrl-C stops)"
  run_backend_fg
  exit 0
fi

# 4a. --dev — backend (background) + Vite dev server (foreground, hot reload) at :5173.
if [[ "$MODE" == dev ]]; then
  echo "• starting backend on :$BACKEND_PORT  (log: src/log/backend.out)"
  start_backend_bg
  command -v npm >/dev/null || { echo "npm not found" >&2; exit 1; }
  [[ -d "$SRC/frontend/node_modules" ]] || ( cd "$SRC/frontend" && npm install )
  echo; echo "  Web app (dev):  http://localhost:$FRONTEND_PORT"
  echo "  Token:          operator=$OPERATOR_TOKEN  expert=$EXPERT_TOKEN"; echo
  echo "• starting Vite dev server on :$FRONTEND_PORT  (Ctrl-C stops both)"
  cd "$SRC/frontend"
  VITE_API_TARGET="http://localhost:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT"
  exit 0
fi

# 4b. Default single-origin — build the UI, then the backend serves it at :8000.
build_frontend
echo; echo "  Web app:  http://localhost:$BACKEND_PORT   (UI + API, one origin)"
echo "  Token:    operator=$OPERATOR_TOKEN  expert=$EXPERT_TOKEN  (enter in the app's login field)"; echo
echo "• starting backend on :$BACKEND_PORT  (serves UI + API; Ctrl-C stops)"
run_backend_fg
