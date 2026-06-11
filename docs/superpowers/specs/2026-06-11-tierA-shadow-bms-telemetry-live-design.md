# Tier A (Shadow BMS · Telemetry · Live Dashboard) + B4 (Live Recirculation) — Design Spec

- **Date:** 2026-06-11 · **Stage:** 5th
- **Goal:** close the loop toward reality, operator-smooth: a shadow-mode BMS adapter seam,
  a real-telemetry ingestion path (with a simulated feed so everything works today), a live
  monitoring dashboard with alerts + setpoint compliance, and a live/calibratable
  recirculation fraction.
- **Reality constraint:** no physical BMS exists on this rig. Everything is built against the
  *seam*: shadow mode records (never actuates), telemetry accepts pushes from any historian
  AND self-generates a simulated feed, all simulated data is explicitly labelled.

## A1 — Shadow-mode BMS adapter

**`src/planner/bms.py`** (new):
- `ShadowBmsAdapter.apply(setpoints, week_start, out_dir) -> dict` — expands the 3 global
  setpoints to the **45 per-actuator commands** (via `broadcast.gds_action_spec` names),
  writes `out_dir/bms_commands.json`:
  `{"mode":"shadow","week_start":…,"written_at":…,"commands":[{"point","value","unit"}×45],"actuated":false}`
  and returns `{"mode":"shadow","n_commands":45,"artifact":…}`. **Never actuates.**
- `BacnetBmsAdapter` placeholder raising `NotImplementedError` with a docstring naming the
  config it will need (host, device map) — the field seam, explicit.

**`src/deploy.py`** `deploy(..., bms=None)`: when a `bms` adapter is passed, call
`bms.apply(...)` (artifact under `runs/<id>/deploy/`) and stamp the rec with
`"deploy_mode":"shadow", "bms": <apply result>, "realized_source":"sim"`. The realized week
still comes from the perturbed-plant oracle run (the observation stand-in) — calibration
keeps learning. Schema bump **1.8** (additive: `deploy_mode`, `bms`, `realized_source`;
older readers unaffected).

**`src/webapp/jobs.py`** `run_deploy_job`: build `ShadowBmsAdapter` when
`DTWIN_DEPLOY_MODE=shadow` (the webapp's default — set in `main.create_app` via
`os.environ.setdefault`); `"sim"` keeps today's exact behavior (tests unchanged).

## A2 — Telemetry ingest

**`src/webapp/telemetry.py`** (new):
- `TelemetryStore(db_path)` — SQLite `telemetry(ts REAL, point TEXT, value REAL)` +
  index on (point, ts). `write(points: dict, ts=None)`, `latest() -> {point:{"ts","value"}}`,
  `series(points, minutes, max_rows≈400/point)` (stride-downsampled).
- `SimTelemetryFeed(store, interval_s=5)` — daemon thread; each tick writes a labelled
  snapshot: 22 rack inlets `rack_inlet_c/ite-N` (base from the latest deployed plan's
  realized inlet, per-rack offsets + slow sinusoid + noise), `hall_power_kw`, `pue`,
  `rh_pct`, held setpoints `held/sat_c|flow_kg_s|chwst_c` (commanded ± small noise), and
  `simulated=1.0`. Started in `create_app` only when `DTWIN_SIM_TELEMETRY=1` (the dev/demo
  default in clear-and-run + driver; **off in tests**).
- Real-historian seam: **`POST /api/telemetry`** (operator) `{ts?, points:{name:value}}` →
  store. A field collector pushes the same names; the sim feed simply stops being started.

**Routes (main.py):**
- `GET /api/live` → `{ts, points:{...latest}, alerts:[{level:"warn|critical", point, value,
  message}], compliance:{commanded:{sat,flow,chwst}|null, held:{...}|null,
  ok:bool|null, deltas}, simulated:bool}`. Alerts: rack inlet ≥ 25.0 → warn ("margin < 1 °C"),
  ≥ 26.0 → critical. Compliance: commanded from the latest deployed plan's rec; tolerance
  0.5 (each axis).
- `GET /api/live/stream` → SSE of the same frame (reuse the plan-stream pattern: poll-diff,
  keepalive, bounded).
- `GET /api/live/series?minutes=30` → series for `hall_power_kw`, `pue`, worst rack inlet
  per sample (server-side max).

## A3 — Live dashboard (operator-smooth)

**`src/frontend/src/pages/Live.tsx`** (new page, nav tab "Live" between Dashboard and New Plan):
- **Alert banner** (top, red/amber) when alerts active; quiet green "all racks nominal" line otherwise.
- **Rack heat-map**: 22 tiles (ite-1…22), color by inlet (green <24.5, amber <25.5, red ≥25.5,
  pulsing border ≥26), temp on tile. Tooltip = point name.
- **KPI tiles**: hall power (kW), PUE, RH, worst inlet + margin-to-cap.
- **Setpoint compliance card**: commanded vs held (SAT/flow/CHWST) with per-axis ✓/⚠ and deltas;
  "no deployed plan" empty state.
- **Rolling chart** (30 min): hall power + worst inlet (Recharts, two axes, 26 °C refline).
- SSE with the NewPlan reconnect pattern; 5 s poll fallback; "SIMULATED FEED" badge when
  `simulated` (honesty in the UI). Vitest coverage incl. alert + compliance states.

## B4 — Live recirculation (planner-side, calibratable)

**`src/planner/recirc.py`** (new):
- `estimate_recirc_fraction(rows) -> {"r": float, "n": int, "r_per_rack": {...}}` — from
  telemetry tuples `(inlet_c, supply_c, return_c)` via the mixing identity
  `r = (T_inlet − T_supply)/(T_return − T_supply)`, clipped [0, 0.5], robust median;
  rows with |T_return − T_supply| < 1 °C discarded.
- `flow_shortfall_recirc(r0, flow_kg_s, demand_kg_s, k=0.5, r_max=0.5)` — containment
  physics: `r_eff = min(r_max, r0 + k·max(0, 1 − flow/demand))` — recirc rises when CRAH
  airflow undershoots ITE demand. Pure + unit-tested.
- `inlet_with_recirc(inlet_pred, zone_c, r0, r_eff)` — post-oracle correction:
  `inlet + (r_eff − r0)·max(0, zone_c − inlet)`; with `r_eff=r0` (flow ≥ demand) it is the
  identity, so current behavior is unchanged until flow undershoots.
- **Safety integration (objective layer):** `oracle`-side KPI adjustment hook in
  `pipeline.run_weekly_plan` — compute `r_eff` from the candidate's flow vs the hall design
  demand (22×design ITE flow from room2ite / config constant) and apply the inlet
  correction **before** feasibility, so low-flow candidates carry an honest recirc penalty.
  Conservative-only (correction ≥ 0), so it can only tighten safety — never weaken.
- **`src/fit_recirc.py`** (CLI): pull rack-inlet + supply/return telemetry from the
  TelemetryStore (or CSV), run `estimate_recirc_fraction`, print + optionally write the
  fitted `r` back via the existing `scripts/recouple_ite_recirc.py` machinery and into
  `data/recirc.json` (consumed by the planner hook as `r0`; default 0.10 when absent).

## Operator-smoothness requirements (acceptance)

1. `scripts/clear-and-run.sh` / driver `start` → Live tab works immediately (sim feed on,
   labelled). No config. Alerts and compliance visible at a glance.
2. Deploy flow unchanged for the operator; Review shows "shadow" mode + a one-line
   "45 commands recorded (not actuated)" note. No new required inputs.
3. All simulated data visibly labelled; the real-data path is one env var + a POST endpoint.
4. Everything TDD; suites + build green; driver smoke still passes; Live page screenshot
   verified.

## Milestones / file ownership (parallel-safe)

| # | Owner files | Out of bounds |
|---|---|---|
| A1 | `planner/bms.py`, `deploy.py`, `webapp/jobs.py`, their tests | main.py, frontend |
| A2 | `webapp/telemetry.py`, `webapp/main.py` (routes only), tests | jobs.py, frontend |
| A3 | `frontend/src/**` (Live.tsx, api.ts, App.tsx, tests) | all backend |
| B4 | `planner/recirc.py`, `planner/pipeline.py` (hook), `fit_recirc.py`, tests | webapp, frontend |
