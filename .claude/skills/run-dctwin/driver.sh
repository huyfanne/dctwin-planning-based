#!/usr/bin/env bash
# driver.sh — agent harness for the DCTwin webapp (FastAPI + React SPA + EnergyPlus oracle).
#
#   driver.sh start            start a fresh backend (kills any old one) and wait healthy
#   driver.sh smoke            curl-based end-to-end smoke (API + create/cancel/delete a real plan)
#   driver.sh smoke --api-only same, but skip the plan lifecycle (no Docker needed)
#   driver.sh plan             run a REAL tiny EnergyPlus plan to completion (~6-8 min)
#   driver.sh screenshot       headless-chromium screenshots: login + dashboard
#   driver.sh status           backend pid / port / active plans / E+ containers
#   driver.sh unstick <id>     recover a wedged running plan (kills its pool workers)
#   driver.sh stop             kill the backend and free the port
#
# Env overrides: PORT (default 8001 — 8000 is often squatted by a foreign container),
#                OPERATOR_TOKEN / EXPERT_TOKEN (default op-secret / ex-secret).
set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"
SRC="$ROOT/src"
PY="$ROOT/.venv-dtwin/bin/python"
PORT="${PORT:-8001}"
OP="${OPERATOR_TOKEN:-op-secret}"
EX="${EXPERT_TOKEN:-ex-secret}"
BASE="http://localhost:$PORT"
LOG="$SRC/log/backend.out"
SHOTS="$SRC/log/screens"

say()  { printf '%s\n' "$*"; }
die()  { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
api()  { curl -s -H "Authorization: Bearer $OP" "$@"; }
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

backend_pids() {
  # anchored: only OUR venv's uvicorn, never this shell (pgrep excludes itself)
  pgrep -f "$PY -m uvicorn webapp.main:app" 2>/dev/null || true
}

cmd_stop() {
  local pids; pids=$(pgrep -f "uvicorn webapp.main:app" 2>/dev/null | grep -vE "^($$|$PPID)$" || true)
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null && say "killed backend procs: $(echo $pids | wc -w)"
  fuser -k "$PORT/tcp" 2>/dev/null || sg docker -c "fuser -k $PORT/tcp" 2>/dev/null || true
  sleep 1
  ss -ltn 2>/dev/null | grep -q ":$PORT " && die "port $PORT still held" || say "port $PORT free"
}

cmd_start() {
  [ -x "$PY" ] || die "venv python missing at $PY"
  [ -f "$SRC/frontend/dist/index.html" ] || \
    say "WARN: frontend not built — '/' will show a hint page. Build: npm --prefix $SRC/frontend run build"
  cmd_stop >/dev/null 2>&1 || true
  mkdir -p "$SRC/log"
  # sg docker: the oracle needs the docker group; env -C because a leading cd is
  # stripped by the agent sandbox. Detached so it survives the shell.
  nohup sg docker -c "env -C $SRC PYTHONPATH=$SRC OPERATOR_TOKEN=$OP EXPERT_TOKEN=$EX \
    $PY -m uvicorn webapp.main:app --host 0.0.0.0 --port $PORT" > "$LOG" 2>&1 &
  disown
  local i=0
  until [ "$(code -H "Authorization: Bearer $OP" "$BASE/api/plans")" = "200" ] || [ $i -ge 30 ]; do
    sleep 1; i=$((i+1))
  done
  [ $i -lt 30 ] || { tail -5 "$LOG" >&2; die "backend not healthy after 30s (log: $LOG)"; }
  say "backend up on $BASE after ${i}s (log: $LOG)"
}

_check() {  # _check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then say "  ok   $1"; else say "  FAIL $1 (expected $2, got $3)"; FAILS=$((FAILS+1)); fi
}

cmd_smoke() {
  local api_only=0; [ "${1:-}" = "--api-only" ] && api_only=1
  FAILS=0
  say "[1/4] UI + auth"
  local title; title=$(curl -s "$BASE/" | grep -o "<title>[^<]*" | head -1)
  _check "GET / serves the SPA"            "yes" "$( [[ "$title" == *DCTwin* ]] && echo yes || echo no )"
  _check "no token -> 401 (fail-closed)"   "401" "$(code "$BASE/api/plans")"
  _check "operator token -> 200"           "200" "$(code -H "Authorization: Bearer $OP" "$BASE/api/plans")"
  say "[2/4] read endpoints"
  _check "GET /api/weather"                "200" "$(code -H "Authorization: Bearer $OP" "$BASE/api/weather")"
  local crahs; crahs=$(api "$BASE/api/topology" | $PY -c "import sys,json; print(len(json.load(sys.stdin)['crahs']))" 2>/dev/null)
  _check "topology has 22 controlled CRAHs" "22" "${crahs:-err}"
  local fsteps; fsteps=$(api "$BASE/api/planning-context?week_start=2024-11-08&days=7" | \
    $PY -c "import sys,json; print(len(json.load(sys.stdin)['it_load']['forecast']))" 2>/dev/null)
  _check "planning-context forecast steps"  "672" "${fsteps:-err}"
  _check "GET /api/calibration"            "200" "$(code -H "Authorization: Bearer $OP" "$BASE/api/calibration")"
  say "[3/4] weather guardrail"
  _check "out-of-coverage week -> 422"     "422" "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/plans" \
      -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
      -d '{"week_start":"2026-06-08","days":2}')"
  if [ $api_only -eq 1 ]; then
    say "[4/4] plan lifecycle skipped (--api-only)"
  else
    say "[4/4] plan lifecycle (create -> running -> cancel -> delete; needs Docker)"
    local pid; pid=$(curl -s -X POST "$BASE/api/plans" -H "Authorization: Bearer $OP" \
      -H "Content-Type: application/json" \
      -d '{"week_start":"2024-11-08","days":2,"grid":2,"beam_width":2,"levels":1,"n_workers":4}' | \
      $PY -c "import sys,json; print(json.load(sys.stdin).get('plan_id',''))")
    [ -n "$pid" ] || { say "  FAIL plan create"; FAILS=$((FAILS+1)); }
    if [ -n "$pid" ]; then
      say "       plan: $pid"
      local i=0 st=""
      until [ "$st" = "running" ] || [ $i -ge 30 ]; do
        st=$(api "$BASE/api/plans/$pid" | $PY -c "import sys,json; print(json.load(sys.stdin)['status'])"); sleep 2; i=$((i+1))
      done
      _check "plan reaches running" "running" "$st"
      _check "cancel accepted"      "202" "$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $OP" "$BASE/api/plans/$pid/cancel")"
      i=0
      until [ "$st" = "cancelled" ] || [ $i -ge 60 ]; do
        st=$(api "$BASE/api/plans/$pid" | $PY -c "import sys,json; print(json.load(sys.stdin)['status'])"); sleep 3; i=$((i+1))
      done
      _check "plan reaches cancelled" "cancelled" "$st"
      _check "delete cleaned up"      "200" "$(curl -s -o /dev/null -w "%{http_code}" -X DELETE -H "Authorization: Bearer $OP" "$BASE/api/plans/$pid")"
    fi
  fi
  [ $FAILS -eq 0 ] && say "SMOKE PASS" || die "$FAILS smoke check(s) failed (backend log: $LOG)"
}

cmd_plan() {
  say "launching a REAL tiny EnergyPlus plan (2 days, grid 2 -> ~25-35 E+ runs, ~6-8 min)…"
  local pid; pid=$(curl -s -X POST "$BASE/api/plans" -H "Authorization: Bearer $OP" \
    -H "Content-Type: application/json" \
    -d '{"week_start":"2024-11-08","days":2,"grid":2,"beam_width":2,"levels":1,"n_workers":6}' | \
    $PY -c "import sys,json; print(json.load(sys.stdin)['plan_id'])") || die "create failed"
  say "plan: $pid — polling to terminal (max 15 min)"
  local i=0 st="queued"
  while [ "$st" = "queued" ] || [ "$st" = "running" ]; do
    [ $i -ge 90 ] && die "plan still $st after 15 min — try: driver.sh unstick $pid"
    sleep 10; i=$((i+1))
    st=$(api "$BASE/api/plans/$pid" | $PY -c "import sys,json; print(json.load(sys.stdin)['status'])")
    say "  t=$((i*10))s status=$st $(cat "$SRC/runs/$pid/progress.json" 2>/dev/null || true)"
  done
  say "FINAL: $st"
  api "$BASE/api/plans/$pid" | $PY -c "
import sys, json
d = json.load(sys.stdin); r = d.get('recommendation') or {}
pk = r.get('predicted_kpis') or {}
print('setpoints:', json.dumps(r.get('setpoints')))
print('energy:', pk.get('total_hvac_energy_kwh'), '| reduction%:', pk.get('energy_reduction_vs_baseline_pct'))"
}

cmd_screenshot() {
  mkdir -p "$SHOTS"
  env -C "$SRC/frontend" node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  await p.goto('$BASE/', { waitUntil: 'networkidle' });
  await p.screenshot({ path: '$SHOTS/login.png' });
  await p.fill('input[type=password]', '$OP');
  await p.click('button[type=submit]');
  await p.waitForSelector('text=Dashboard', { timeout: 10000 });
  await p.waitForTimeout(1500);
  await p.screenshot({ path: '$SHOTS/dashboard.png', fullPage: true });
  await b.close();
  console.log('screenshots: $SHOTS/login.png  $SHOTS/dashboard.png');
})().catch(e => { console.error(e.message); process.exit(1); });
" || die "screenshot failed (is the backend up? is the frontend built?)"
}

cmd_status() {
  say "backend pids: $(backend_pids | tr '\n' ' ')"
  say "port $PORT: $(ss -ltn 2>/dev/null | grep -q ":$PORT " && echo LISTENING || echo free)"
  api "$BASE/api/plans" 2>/dev/null | $PY -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception: print('API not reachable'); raise SystemExit
act = [p for p in d if p['status'] in ('queued','running','deploying')]
print(f'plans: {len(d)} total, {len(act)} active', *(f\"  {p['plan_id']} {p['status']}\" for p in act), sep='\n')" || true
  say "E+ containers: $(sg docker -c 'docker ps -q --filter ancestor=ierg4910/eplus95:latest' 2>/dev/null | wc -l)"
}

cmd_unstick() {
  local plan="${1:?usage: driver.sh unstick <plan_id>}"
  # only act on a plan that is actually live — killing children of a healthy backend
  # would hit the multiprocessing resource tracker / mid-flight workers
  local st; st=$(api "$BASE/api/plans/$plan" | \
    $PY -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
  [ "$st" = "running" ] || [ "$st" = "queued" ] || \
    die "plan $plan is '${st:-unknown}', not running/queued — nothing to unstick"
  local main; main=$(pgrep -of "$PY -m uvicorn webapp.main:app") || die "no backend running"
  local workers="" c
  for c in $(pgrep -P "$main" 2>/dev/null); do
    ps -o args= -p "$c" 2>/dev/null | grep -q "resource_tracker" && continue
    workers="$workers $c"
  done
  [ -n "${workers// /}" ] || die "no pool workers under backend $main — the wedge may be elsewhere (see $LOG)"
  say "killing pool workers of backend $main:$workers"
  kill -9 $workers 2>/dev/null
  say "the executor now fails the stuck futures -> candidates marked infeasible -> the plan"
  say "continues (or a pending cancel completes). Check: driver.sh status / progress.json of $plan"
}

case "${1:-}" in
  start)      cmd_start ;;
  stop)       cmd_stop ;;
  smoke)      shift; cmd_smoke "$@" ;;
  plan)       cmd_plan ;;
  screenshot) cmd_screenshot ;;
  status)     cmd_status ;;
  unstick)    shift; cmd_unstick "$@" ;;
  *)          grep '^#   driver' "$0" | sed 's/^#   //'; exit 1 ;;
esac
