#!/usr/bin/env bash
#
# clear-and-run.sh — wipe plan state, then start the backend + frontend.
#
# Usage:
#   scripts/clear-and-run.sh [--keep-runs] [-y|--yes]
#                            [--backend-only | --frontend-only] [-h|--help]
#
# Env overrides (with defaults):
#   OPERATOR_TOKEN=op-secret   EXPERT_TOKEN=ex-secret
#   BACKEND_PORT=8000          FRONTEND_PORT=5173
#
# The backend runs EnergyPlus via Docker, so it launches under `sg docker`.
# Frontend runs in the foreground; Ctrl-C stops BOTH (cleanup trap).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="$ROOT/src"
PY="$ROOT/.venv-dtwin/bin/python"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
OPERATOR_TOKEN="${OPERATOR_TOKEN:-op-secret}"
EXPERT_TOKEN="${EXPERT_TOKEN:-ex-secret}"

CLEAR_RUNS=1; ASSUME_YES=0; START_BACKEND=1; START_FRONTEND=1
for arg in "$@"; do
  case "$arg" in
    --keep-runs)     CLEAR_RUNS=0 ;;
    -y|--yes)        ASSUME_YES=1 ;;
    --backend-only)  START_FRONTEND=0 ;;
    --frontend-only) START_BACKEND=0 ;;
    -h|--help)       sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown arg: $arg (try --help)" >&2; exit 2 ;;
  esac
done

kill_port() { lsof -ti:"$1" 2>/dev/null | xargs -r kill 2>/dev/null || true; }

# 1. Stop anything already on the ports.
echo "• stopping servers on :$BACKEND_PORT and :$FRONTEND_PORT"
kill_port "$BACKEND_PORT"; kill_port "$FRONTEND_PORT"

# 2. Clear state (runs/ + index.db are recreated on the next plan).
if [[ "$CLEAR_RUNS" == 1 && "$ASSUME_YES" != 1 ]]; then
  read -r -p "Delete ALL plans in $SRC/runs (irreversible)? [y/N] " ans || ans=""
  [[ "$ans" =~ ^[Yy]$ ]] || { CLEAR_RUNS=0; echo "  keeping runs/"; }
fi
if [[ "$CLEAR_RUNS" == 1 ]]; then
  rm -rf "$SRC/runs"; echo "• cleared runs/ (plans + index.db)"
  rm -f "$SRC"/log/* 2>/dev/null || true
fi
rm -rf "$SRC/frontend/.vite" "$SRC/frontend/dist" 2>/dev/null || true

# On exit (incl. Ctrl-C from the foreground frontend), tear both down.
cleanup() { echo; echo "• stopping…"; kill_port "$BACKEND_PORT"; kill_port "$FRONTEND_PORT"; }
trap cleanup EXIT INT TERM

# 3. Backend (background, logged).
if [[ "$START_BACKEND" == 1 ]]; then
  [[ -x "$PY" ]] || { echo "interpreter not found: $PY" >&2; exit 1; }
  mkdir -p "$SRC/log"
  echo "• starting backend on :$BACKEND_PORT  (log: src/log/backend.out)"
  sg docker -c "cd '$SRC' && PYTHONPATH='$SRC' OPERATOR_TOKEN='$OPERATOR_TOKEN' EXPERT_TOKEN='$EXPERT_TOKEN' \
    '$PY' -m uvicorn webapp.main:app --host 0.0.0.0 --port $BACKEND_PORT" \
    > "$SRC/log/backend.out" 2>&1 &
  for _ in $(seq 1 30); do
    lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1 && { echo "  backend listening"; break; }
    sleep 1
  done
  lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1 || echo "  (backend not up yet — check src/log/backend.out)"
fi

echo
echo "  Web app:  http://localhost:$FRONTEND_PORT"
echo "  Token:    operator=$OPERATOR_TOKEN   expert=$EXPERT_TOKEN  (enter in the app's login field)"
echo

# 4. Frontend (foreground; keeps the script alive so the trap can stop the backend).
if [[ "$START_FRONTEND" == 1 ]]; then
  command -v npm >/dev/null || { echo "npm not found" >&2; exit 1; }
  [[ -d "$SRC/frontend/node_modules" ]] || ( cd "$SRC/frontend" && npm install )
  echo "• starting frontend on :$FRONTEND_PORT  (Ctrl-C stops both)"
  cd "$SRC/frontend"
  VITE_API_TARGET="http://localhost:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT"
elif [[ "$START_BACKEND" == 1 ]]; then
  echo "• backend-only — tailing log (Ctrl-C to stop)"
  tail -f "$SRC/log/backend.out"
fi
