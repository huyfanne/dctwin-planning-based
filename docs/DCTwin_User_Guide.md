# DCTwin User & Developer Guide

DCTwin is a **digital-twin dual-loop optimizer for weekly data-center cooling setpoints**. Each week it searches three global setpoints — CRAH supply-air temperature (**SAT**, 20–26 °C), CRAH airflow (**flow**, 4.8–13.8 kg/s), and chilled-water supply temperature (**CHWST**, 13–19 °C) — and scores every candidate with a **full-week EnergyPlus 9.5 run executed in Docker** (the *oracle*), not a surrogate model. The 3 global setpoints are broadcast to **45 actuators** (22 SAT + 22 FLOW + 1 CHWST) for the controlled 1F-2A hall. A **hard safety invariant — rack inlet temperature ≤ 26 °C at every timestep — is non-negotiable** and enforced by a layered "three-net" safety gate. An inner *planning loop* (forecast → beam search → oracle → robust gate → recommendation) proposes a plan; an outer *deployment loop* (pre-validate → expert approve → deploy → calibrate) closes the fidelity gap and feeds learning back into the next week.

---

## System at a glance

```
                        ┌──────────────────────────── FORECASTERS ────────────────────────────┐
                        │  IT-load (persistence / seasonal-climatology)  +  weather (EPW        │
                        │  historical-analog spread → hot/cool scenarios)                       │
                        └───────────────────────────────┬─────────────────────────────────────┘
                                                         │ Forecast(workload_schedules, weather_file, bands)
                                                         ▼
  ┌──────────────────────────── INNER PLANNING LOOP (per week) ──────────────────────────────────┐
  │                                                                                                │
  │   coarse grid ──► beam search ──► EnergyPlus ORACLE ──► objective + feasibility ──► robust gate │
  │   (g³ candidates)  (refine L lvls)  (Docker, full week)  (energy + soft pen, ≤26°C)  (3 nets)   │
  │        types.py     beam_search.py    oracle.py /          objective.py              robust.py   │
  │                                       oracle_worker.py                                          │
  │                                                                                                │
  │   3 global setpoints ──broadcast.py──► 45 actuators ──► EnergyPlus actions                      │
  └────────────────────────────────────────────────┬───────────────────────────────────────────┘
                                                     │ recommendation.json (status: pending_approval / blocked_unsafe / …)
                                                     ▼
  ┌──────────────────────────── OUTER DEPLOYMENT LOOP ───────────────────────────────────────────┐
  │   pre-validation ──► EXPERT review/approve ──► deploy (shadow BMS) ──► realized KPIs            │
  │   prevalidation.py     webapp (Review.tsx)      deploy.py + bms.py       realized.json          │
  │        │                                              │                       │                 │
  │        └──────────────── calibration (bias/σ) + physics recalibration ◄───────┘                │
  │                          calibrator.py / recalibrator.py  →  next week's search & ensemble      │
  └──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                     ▲
  ┌──────────────────────────── WEB APPLICATION (FastAPI + React) ───────────────────────────────┐
  │  operator/expert tokens · JobRunner (1 worker thread) · SSE progress + live telemetry          │
  │  pages: Dashboard · NewPlan · Review · Live · History · DigitalTwin3D                           │
  └────────────────────────────────────────────────────────────────────────────────────────────┘
```

The two loops share one EnergyPlus oracle and one calibration state. The web app is the human-facing skin over both loops; the forecasters supply the workload + weather inputs the oracle simulates against.

---

## Repository layout

| Path | Purpose |
|---|---|
| `src/planner/` | The inner planning loop: beam search, oracle, objective, robust gate, forecasters, calibration, baseline, broadcast, schedule. |
| `src/webapp/` | FastAPI backend: routes (`main.py`), job runner (`jobs.py`), SQLite store (`store.py`), auth (`auth.py`), status state machine (`status.py`), telemetry (`telemetry.py`), 3D topology (`topology.py`). |
| `src/frontend/` | React 19 + Vite + TypeScript UI. `src/pages/` (Dashboard, NewPlan, Review, Live, History, DigitalTwin3D), `src/three/` (3D scene), `src/api.ts` (client). |
| `src/*.py` (CLI) | `plan_weekly.py`, `fit_forecaster.py`, `prevalidation.py`, `deploy.py`, `fit_recirc.py`, `backtest_forecaster.py`. |
| `dctwin/` | The EnergyPlus/BCVTB co-simulation engine: `registration.py` (`make_env`), `gym_envs/eplus_env.py`, `third_parties/eplus/core.py`, `third_parties/docker_backend.py`. |
| `src/runs/` | Per-week result artifacts (`gds-2024-MM-DD-HASH/`): `recommendation.json`, `realized.json`, `oracle/`, `robust/`, `prevalidation/`, `deploy/`, `plant/`. |
| `src/log/` | Operational logs (planning, oracle, diagnostics, sweeps, screenshots, `backend.out`). |
| `models/`, `configs/`, `data/` | Planner assets (gitignored): `forecaster.pkl`, `dt.prototxt`, `calibration.json`, EPW weather, `his_data_processed.csv`, etc. Copy the GDS model from `mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup`. |
| `docs/superpowers/specs/` & `docs/superpowers/plans/` | Design specs + TDD implementation plans (dated spec+plan pairs per shipped tier). |
| `graphify-out/` | AST knowledge graph of `src/` (`GRAPH_REPORT.md`, `graph.html`, `graph.json`). |
| `dctwin/BHUMANS/` | Report assets: figures (`deck_assets/figA…figF.png`), decks, manuscript, review notes. |
| `scripts/clear-and-run.sh` | One-command launcher (clears state, builds frontend, serves the whole app). |

---

## Quick start (operators)

### Environment

DCTwin uses a non-standard virtualenv and a sandboxed shell. Two rules:

- **Python interpreter:** always `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`. There is no `python`/`python3` on PATH with the deps. The backend shares this venv so it can run real EnergyPlus plans.
- **`cd` quirk:** a leading `cd` is stripped from shell commands. Use `env -C <dir> …` or `git -C <repo> …` instead.
- The Python package roots are under `src/` (`from planner…`, `from webapp…`). Run from `src/` or set `PYTHONPATH=…/src`.
- **Docker** is needed only to *run* a plan (it launches EnergyPlus). Wrap those commands in `sg docker -c "…"`.

### Step 1 — Fit the forecaster (once, offline)

A fitted forecaster is **required before any plan**. It builds the room→column mapping and pickles a config to `models/forecaster.pkl`.

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python fit_forecaster.py
```

To thread a weather file and pick the seasonal method:

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c \
  "import fit_forecaster; fit_forecaster.main(weather_file='data/weather/Singapore_Changi_Nov2024-Jan2025.epw')"
```

### Step 2 — Run the web app

The simplest path clears plan state, builds the UI, and serves the **whole app from one origin** at `http://localhost:8000` (UI at `/`, API at `/api/*`):

```bash
scripts/clear-and-run.sh            # → http://localhost:8000  (single origin)
scripts/clear-and-run.sh --dev      # → http://localhost:5173  (Vite hot reload + backend proxy)
```

To start the backend by hand (Docker group, both role tokens):

```bash
sg docker -c "env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src PYTHONPATH=\$PWD \
  OPERATOR_TOKEN=op EXPERT_TOKEN=ex \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m uvicorn webapp.main:app --port 8000"
```

`webapp/main.py` mounts `frontend/dist` at `/` only when it's built — so run `npm --prefix src/frontend run build` (or `clear-and-run.sh` does it for you), or `/` shows a "not built" hint instead of the UI.

### Step 3 — The end-to-end operator workflow

| # | Action | Who | UI page / endpoint |
|---|---|---|---|
| 1 | Paste token, log in | operator/expert | Login → `GET /api/plans` (verify) |
| 2 | Create a new weekly plan (`week_start`, `days`, search params) | operator | NewPlan → `POST /api/plans` |
| 3 | Watch live search progress (level, evals, best score) | operator | NewPlan → SSE `GET /api/plans/{id}/stream` |
| 4 | Review setpoints, predicted KPIs, baseline comparison, robust bands, trajectory | expert | Review → `GET /api/plans/{id}` |
| 5 | (optional) Edit setpoints — invalidates prevalidation, blocks approval | expert | Review → `PATCH /api/plans/{id}/setpoints` |
| 6 | Approve (or reject) | expert | Review → `POST /api/plans/{id}/approve` |
| 7 | Deploy the approved plan (shadow mode) | expert | Review → `POST /api/plans/{id}/deploy` |
| 8 | Monitor live racks / power / compliance | operator | Live → `GET /api/live`, SSE `/api/live/stream` |

The equivalent headless CLI flow (from `src/README.md`):

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src ... python plan_weekly.py --week-start 2024-11-11
env -C ... python prevalidation.py --recommendation runs/<id>/recommendation.json            # validate
env -C ... python prevalidation.py --recommendation runs/<id>/recommendation.json --approve  # expert approve
# deploy: deploy(rec_path, ParallelEnvOracle(...))  — runs the plant week, records realized KPIs
```

### How to read results

- **Predicted vs realized energy:** `recommendation.json → predicted_kpis` vs `realized.json → total_hvac_energy_kwh`. The week's prediction error is the gap.
- **Savings:** `energy_reduction_vs_baseline_pct` in `predicted_kpis` = `(baseline_kwh − plan_kwh) / baseline_kwh × 100`.
- **Safety:** `realized.json → inlet_temp_max_c` (must be ≤ 26.0) and `inlet_violation_steps` (must be 0). Any violation flips deploy status to `deploy_blocked`.
- **Status:** `recommendation.json → status` is the plan's place in the state machine (see [Web application](#web-application--operator-workflow)).

---

## The inner planning loop

The inner loop turns a `PlanRequest` + forecast into a `recommendation.json`. Its core orchestrator is `run_weekly_plan()` (`src/planner/pipeline.py:62`), which builds a `BeamPlanner`, runs the search, applies the calibration forecast margin, optionally reranks finalists through the robust ensemble, and falls back to the safety ladder when the optimum is fragile.

### 5.1 Beam search, objective & constraints

**What it does.** A best-first **coarse-to-fine** search over the 3D setpoint space. Level 0 evaluates a `grid³` coarse grid; subsequent levels generate local neighbors around each beam node with a halving step. Every candidate is scored against a single scalar objective with a hard feasibility gate.

The objective (`src/planner/objective.py:47`, minimized over feasible candidates):

```
score(kpi) = energy_term
           + λ_temp · inlet_excess_degc_steps     (default λ_temp = 1.0)
           + λ_rh   · rh_excursion_steps           (default λ_rh   = 0.2)
           + λ_zone · zone_temp_band_steps         (default λ_zone = 0.1)
         = INFEASIBLE (math.inf) if not is_feasible(kpi)
```

`energy_term` is `kpi.total_hvac_energy_kwh`, or `kpi.weighted_energy_cost` when a tariff is loaded (the two never combine — it's pure kWh or pure cost/carbon). The soft-penalty accumulators are computed **by the oracle**, not the objective; the objective only sums them. Infeasible candidates score `+inf` and sink to the bottom of the stable sort, so they can never enter the beam (`_top_b`, `beam_search.py:170`).

The hard feasibility gate `is_feasible()` (`objective.py:35`) is conjunctive — **all** must hold:

1. `kpi.feasible == True` (simulator converged, no physical error).
2. `inlet_violation_steps ≤ inlet_tol_steps` (default tolerance 0 — zero violations).
3. `inlet_temp_max + inlet_forecast_margin ≤ inlet_cap` (default cap 26.0 °C).
4. If `rh_hard == True`: `rh_violation_steps ≤ rh_tol_steps` (off by default).

**Key files.**

| Symbol | Location | Role |
|---|---|---|
| `BeamPlanner.plan` | `src/planner/beam_search.py:85` | Entry point; returns `PlanResult` (best setpoints, score, evals, feasible, history, finalists). |
| `BeamConfig` | `src/planner/beam_search.py:33` | Hyperparameters: `grid=5`, `beam_width=5`, `levels=3`, `neighbors=8`, `max_evals=400`, `epsilon=1e-3`. |
| `_coarse_grid` | `src/planner/beam_search.py:60` | `np.linspace` Cartesian product → g³ candidates. |
| `score` / `is_feasible` | `src/planner/objective.py:47` / `:35` | Scalar objective + hard gate. |
| `ObjectiveWeights` | `src/planner/objective.py:12` | Soft λ weights + hard tolerances (`inlet_cap=26.0`, `inlet_forecast_margin`, `rh_hard`). |
| `DEFAULT_SEARCH_SPACE` | `src/planner/types.py:81` | SAT [20,26], flow [4.8,13.8], CHWST [13,19]. |
| `run_weekly_plan` | `src/planner/pipeline.py:62` | Orchestration. |

**Configure / extend.** Tune the search via `PlanRequest` (`grid`, `beam_width`, `levels` map directly to `BeamConfig`). Tune the objective via `ObjectiveWeights`. There is no callback slot for a custom objective today — to change the energy term, modify `score()` or have the oracle set a different `energy_term` (e.g. via tariff). See [Extending DCTwin](#extending-dctwin-developers).

**Termination & edge cases.** Hard cap at `max_evals`; soft early-stop when the best score improves by less than `epsilon · max(|prev|, 1)`. If the coarse grid shows < 0.1 °C inlet spread **and** < 1 % energy spread, `PlanResult.degenerate_no_signal=True` flags a control-invariant model (any "winner" is noise). If g³ exceeds `max_evals`, the grid is **lexicographic-stride** subsampled (not random) — the first dimension stays fully sampled, the last is sparse.

### 5.2 EnergyPlus oracle & Docker

**What it does.** Scores each candidate with a real full-week EnergyPlus 9.5 simulation, fanned out across **processes** (the dctwin config is a process-global singleton, so threads would corrupt each other's case directories).

**Flow per candidate** (`evaluate_one`, `src/planner/oracle_worker.py:168`):

1. `dctwin.make_env(env_proto_config=week_config_path)` builds a gym `EPlusEnv` (`dctwin/gym_envs/eplus_env.py:18`) wrapping `EplusDockerBackend`.
2. `_configure_backend` points the EnergyPlus container at the reachable BCVTB host and sets the socket timeout to the per-candidate budget.
3. `mapper_from_env` derives the `BroadcastPolicy`; `broadcaster.expand(Setpoints)` maps 3 globals → N normalized actions.
4. `discover_monitor` introspects `env.observations` to find power/thermal/HVAC sensors and scope them to the controlled hall.
5. `run_episode` loops `env.step` to the end of the week, collecting `StepSample`s; `aggregate_kpi` produces the `WeeklyKPI`.
6. A watchdog (`_run_with_timeout`) kills the container on hang to break a blocked `recv()`.

**Co-simulation.** EnergyPlus runs in `ghcr.io/cap-dcwiz/energyplus-9-5-0:latest`; the worker opens a listening socket, writes `socket.cfg`/`variables.cfg`, runs the container (`DockerBackend.run_container`), and exchanges actions/observations over BCVTB each step.

**Key files.**

| Symbol | Location | Role |
|---|---|---|
| `ParallelEnvOracle.evaluate` | `src/planner/oracle.py:107` | Public API; builds an `EvalTask` per candidate, fans out across a `ProcessPoolExecutor`, collects with a stall guard. |
| `OracleConfig` | `src/planner/oracle.py:19` | `n_workers=8`, `timeout_s=300`, `timesteps_per_hour=4`, `bcvtb_host="172.17.0.1"`, `monitored_hall="1f 2a"`. |
| `evaluate_one` | `src/planner/oracle_worker.py:168` | Per-worker episode. |
| `aggregate_kpi` | `src/planner/kpi.py:50` | Aggregates post-warmup samples into `WeeklyKPI`. |
| `discover_monitor` | `src/planner/monitor.py:35` | Sensor discovery + hall scoping. |
| `make_env` | `dctwin/registration.py:9` | prototxt → gym env factory. |
| `EplusBackendMixin` | `dctwin/third_parties/eplus/core.py:23` | BCVTB protocol. |
| `MockEvaluator` | `src/planner/mock_evaluator.py:24` | Fast analytic stand-in for **all unit tests** (no Docker). |

**Configure / extend.** `OracleConfig` controls parallelism and timeouts. **Gotchas to respect:** Docker volume mount paths must be absolute; `bcvtb_host` must be the Docker0 gateway `172.17.0.1` on Linux (not `host.docker.internal`) and set **before** `env.reset()`; the default socket timeout is 1 hour and must be overridden per candidate; `aggregate_kpi` skips the first 6 warmup steps; a week that crosses a calendar-year boundary raises `ValueError` (EnergyPlus hardcodes year 2013).

### 5.3 Candidate generation

**What it does.** Enumerates the candidates the oracle scores, and expands the chosen 3-tuple to the env's 45 actuators.

- **Coarse grid:** `_coarse_grid` (`beam_search.py:60`) produces `grid³` candidates (e.g. 5³ = 125) via `np.linspace` per dimension.
- **Neighbors:** `_neighborhood` (`beam_search.py:174`) emits up to 8 local offsets (±step per dim plus 2D diagonals), clipped to bounds by `SearchSpace.clip` (`types.py:40`). The step halves each refinement level.
- **Broadcast:** `BroadcastPolicy.expand` (`broadcast.py:46`) maps `Setpoints(sat, flow, chwst)` to an N-dim `[-1,1]` vector via `normalize(x, lb, ub) = 2·(x−lb)/(ub−lb) − 1`. The GDS hall is **45 AGENT_CONTROLLED actuators in fixed order `[22 SAT, 22 FLOW, 1 CHWST]`** (`gds_action_spec`, `broadcast.py:59`). A single SAT value replicates to all 22 SAT actuators; same for FLOW; CHWST is global. **This order is load-bearing** — a prototxt reordering silently breaks the mapping.

**Time-block (day/night) scheduling** (opt-in via `PlanRequest.time_block`):

- `TimeBlock`/`WeeklySchedule` (`src/planner/schedule.py`) model per-block constant setpoints with midnight wraparound (`DEFAULT_BLOCKS`: day 6–18, night 18–6).
- `refine_schedule` (`src/planner/schedule_search.py:35`) is a 2-level warm-start coordinate descent **seeded at the constant optimum** — guaranteeing the result is never worse than the constant.
- `evaluate_one_schedule` (`oracle_worker.py:245`) switches the action per simulation hour via `schedule.block_for_hour`.
- The top-level `recommendation.setpoints` mirror the day block for backward compatibility; the full schedule lives in `recommendation["schedule"]` only when `time_block=True`.

### 5.4 Robust "three-net" safety gate

The hard inlet ≤ 26 °C cap binds across **three independent safety layers**, each hedging a distinct uncertainty, with single-counted allocation (no double-hedging).

| Net | Hedges | Mechanism | Location |
|---|---|---|---|
| **1 — k·σ pre-tightening** | twin-vs-plant model error | Search treats the cap as `26 − k·σ`. `apply_forecast_margin` sets `inlet_forecast_margin = K_SIGMA · σ_inlet` (`K_SIGMA=1.0`); candidates breaching the tightened cap score `+inf`. Cold-start σ = `SIGMA_PRIOR=1.0 °C` → search cap 25.0 °C. | `src/planner/pipeline.py:19`, `objective.py:40` |
| **2 — robust scenario ensemble** | plant degradation (fan/coil fouling, wear) | Each finalist is re-simulated across N perturbed-plant scenarios (default 4) whose factors scale by `[1−spread, 1+spread]`. Each scenario KPI is **bias-corrected** then tested against the *hard* cap with `inlet_forecast_margin=0` (no stacking on net 1). A finalist is robust-feasible iff ≥ ⌈N/2⌉ scenarios succeed and all successful ones pass. | `src/planner/robust.py:173`, `robust_select` `:132` |
| **3 — safety-ladder backstop** | energy-optimality traps & discrete failures | If all finalists are fragile, enumerate the energy↔robustness frontier (`safety_ladder`: cheap axes first — CHWST↓, then SAT↓, then full diagonal to the max-cooling corner) and recommend the cheapest provably-robust variant. Only if the max-cooling corner itself fails does status become `blocked_unsafe`. | `src/planner/robust.py:64`, `pipeline.py:129` |

**Ensemble sizing.** `scenario_spread` (`robust.py:44`) scales `base_spread=0.1` by the empirical-Bayes posterior `σ_post / σ_ref`, floored at `MIN_SPREAD=0.02` (the ensemble never collapses below ±2 % drift). `σ_post = sqrt((n·s² + σ_prior²)/(n+1))` — the prior counts as one pseudo-week, so even one accurate week buys only a √2 tightening, never a collapse.

**Configure / extend.** `K_SIGMA`, `SIGMA_PRIOR`, `MIN_SPREAD`, `n_scenarios`, and `inlet_cap=26.0` are the levers. The hard cap is a non-negotiable invariant — **do not weaken these gates to make a search succeed.** Status codes: `pending_approval` (feasible), `blocked_unsafe` (robust-infeasible even after the ladder), `infeasible_fallback` (no feasible candidate under nominal).

---

## The outer deployment loop

### 6.1 Pre-validation

**What it does.** A post-planning, pre-deployment independent replay that re-evaluates the recommended setpoints with a fresh oracle (not the stored `predicted_kpis`) to catch model drift. It runs immediately after planning **inside `run_plan_job`**, but is **advisory — it never fails the plan** (any exception is logged; the plan still reaches `pending_approval`).

`run_prevalidation_with_oracle` (`src/prevalidation.py:68`) runs two scenarios in parallel: a **nominal** replay and a **worst-case** (most-degraded plant from the calibration spread). It compares against a conservative baseline (coolest SAT, max flow, coolest CHW). Verdict: `passes = (inlet_violations == 0) AND (energy_reduction > 0 %)` (`validation_metrics`, `src/planner/validation.py:7`).

**Artifacts** (`runs/<id>/prevalidation/`): `report.md` (PASS/FAIL + KPI table), `trajectory_ai.csv` and `trajectory_worst.csv` (15-min inlet/power/PUE series), plus `oracle/` and `worst/` simulation logs.

**Gotchas.** Setpoint edits set `needs_revalidation=true` and clear `predicted_kpis` but do **not** auto-rerun prevalidation — the expert must run a fresh plan for updated assurance. Approval is blocked while `needs_revalidation=true`. Trajectory CSVs are always 15-min granularity regardless of the planning resolution.

### 6.2 Shadow-mode deployment

**What it does.** `deploy()` (`src/deploy.py:28`) is the approval-guarded backstop. It raises `PermissionError` unless `rec["status"] == "approved"`, then (when a BMS adapter is passed) calls `bms.apply()` and runs the perturbed-plant oracle to record realized KPIs.

The **BMS seam** (`src/planner/bms.py`) has two interfaces:

- `ShadowBmsAdapter.apply` (`bms.py:52`): expands the 3 setpoints into **45 denormalized commands** in GDS order, writes `bms_commands.json` (`mode:"shadow", actuated:false`), and **never actuates** — it only audits.
- `BacnetBmsAdapter` (`bms.py:73`): the field seam, raises `NotImplementedError` documenting the required site config (BACnet host, 45-point device map, write priority).

`bms_adapter_for_mode` (`jobs.py:331`) reads `DTWIN_DEPLOY_MODE` (webapp default `"shadow"`); `"sim"` returns `None` (pre-1.8 pure-sim path). The realized week always comes from the oracle (`realized_source:"sim"`) so calibration keeps learning. Schema **1.8** adds `deploy_mode`, `bms`, `realized_source` additively. The hard 0-tolerance cap applies one final time: any realized inlet violation flips status to `deploy_blocked`.

**Live telemetry & recirculation** ship alongside deployment: `TelemetryStore` (SQLite, `telemetry.py:48`), `SimTelemetryFeed` (daemon, 22 rack inlets + power/PUE/held setpoints every 5 s, always labelled `simulated=1.0`), the `RecircAwareEvaluator` wrapper (`recirc.py:81`, opt-in when `data/recirc.json` calibrates `demand_kg_s > flow.lb`), and `fit_recirc.py` to fit the recirculation fraction `r0` from telemetry.

### 6.3 Physics recalibration

**What it does.** Closes the fidelity loop after each deploy. Two complementary mechanisms:

- **Output-residual calibration** (`calibrator.py`): fits per-KPI additive `bias` (mean of winsorized residuals) and uncertainty `sigma` (fading-floor `max(sample, prior/n)`) + `sigma_post` (empirical-Bayes) from the paired deploy history. `Calibration.apply` (`calibrator.py:43`) corrects each candidate's KPI before scoring, and flags an inlet violation if a corrected inlet exceeds 26 °C. `sigma_for` backs the net-1 margin; `sigma_post_for` sizes the net-2 ensemble.
- **Physics recalibration** (`recalibrator.py`): maps a persistent energy bias to a fan-efficiency factor. `fit_plant_factors` (`recalibrator.py:23`) computes `b = mean(realized/predicted ratios) − 1`, requires ≥ 4 weeks and `|b| ≥ 0.01`, and proposes `factor = clip(1/(1+b), 0.85, 1.15)`. `recalibrate` (`recalibrator.py:48`) writes a perturbation proposal merged over `DEFAULT_PLANT` (fan 0.93×, coil 0.85×) by `load_plant_config` to recenter the next plan's robust ensemble.

**Wiring** (`run_deploy_job`, `jobs.py:344`): after the plant week → `advance_calibration` (append paired predicted/realized) → `recompute_calibration` (refit + persist `calibration.json`) → `write_plant_calibration` (guarded; writes `plant_calibration.json` if drift is actionable). The next plan loads these so its search is bias-corrected and its ensemble centers tighter.

**Invariants.** Residuals are fit against **raw** predictions (`residual_predicted_for`, `jobs.py:296`) to avoid double-correction; recalibration is fully `try/except`-wrapped so a hiccup never fails the deploy; the fading floor never collapses to σ=0.

### 6.4 As-operated baseline

**What it does.** Derives the plant's current control state from telemetry so savings are measured against reality, not a synthetic point. `as_operated_setpoints` (`src/planner/baseline.py:41`) regex-matches multiple CRAH/chiller columns, takes the pooled nanmedian per axis, converts median fan-speed to flow (`flow = (median_fan / fan_speed_max) · design_flow_kg_s_per_acu`), and clips to the search space (silently falling back to mid-range when a signal is absent).

`run_weekly_plan` evaluates the baseline **exactly once** per planning run (`pipeline.py:110`) on the same forecast and calibration as the AI plan, so the energy-reduction comparison is honest. Schema **1.7** records the `baseline` block (`source:"as_operated"`, `energy_kwh`, `setpoints`, `kpis`) and the `energy_scope` label. Loop closure writes two **separate, incompatible** files: `realized_history.csv` (weekly KPI summary) and `calibration_history.json` (paired predicted/realized for residual fitting) — never mix them with the forecaster's per-step IT-load CSV.

---

## Forecasters

The forecasters supply the workload + weather the oracle simulates against. Both are honest naive models (no external provider), reflecting genuine short-horizon uncertainty.

**IT-load forecaster** (`src/planner/forecaster.py`):

- `loading_from_it_loads` normalizes per-hall kW to a 0–1 CPU-loading fraction.
- **Persistence** (`StatisticalForecaster`, `:134`): last-n_steps of the loading series, no calendar awareness.
- **Seasonal** (`SeasonalForecaster`, `:167`): a (weekday × time-of-day) climatology with p10/p50/p90 bands, re-leveled to the calendar period via `calendar_level_scale` (mean in `week_start ± 10 days` / mean of all, clipped [0.5, 1.5]). Falls back to hourly then global percentiles when a bucket has < 4 samples.
- The 1F-2A load is empirically **flat** (mean ~971 kW, span 870.8–1057.9 over ~116 days), so the forecast appears nearly constant — that is **correct**, not a bug. Week-to-week variation is weather-driven. Only the seasonal method populates `forecast.bands`.

**Weather forecaster** (`src/planner/weather_forecast.py`, `epw.py`):

- `weather_stats` (`:33`) extracts the **historical-analog spread** — dry-bulb mean/σ for the target week's month-days (year-agnostic, ±7 days) from the EPW. This is the swap-in seam for a real NWP provider: replace this one function's `{mean_c, sigma_c, n}` return and everything downstream is unchanged.
- `weather_scenarios` (`:95`) generates nominal/hot/cool EPW variants by shifting dry-bulb ±k·σ (k=1.0), clamping dew-point ≤ shifted dry-bulb. The robust gate's hot-weather scenario uses the hot variant.
- `week_within_epw` validates the week fits the EPW coverage; a year-boundary week raises `ValueError` at `write_week_config`.

**Fit & backtest.** `fit_forecaster.py:main` pickles `models/forecaster.pkl` (`{method, his_csv, room2ite_path, his_col_for_room, weather_file}`). `backtest_forecaster.py` reports RMSE/MAPE/PICP on a held-out window (calibrated bands give PICP ≈ 0.8).

**Oracle integration.** The oracle calls `forecast.materialize()` to write per-ITE workload schedules, then `write_week_config(weather_file=forecast.weather_file)` to set the EnergyPlus RunPeriod and weather, optionally lifting ACU masking so the planner can freely optimize.

---

## Web application & operator workflow

A single-origin **FastAPI** backend (port 8000) serves a **React 19 + Vite + TypeScript** frontend built into `dist/` and mounted at `/`. Auth is Bearer-token with two roles: **operator** (creates plans, monitors) and **expert** (approves, edits, deploys). `TokenAuth` (`auth.py:11`) is fail-closed (denies if no tokens configured) unless `DTWIN_INSECURE=1`.

**Backend routes** (selected):

| Method & path | Role | Handler | Purpose |
|---|---|---|---|
| `POST /api/plans` | operator | `create_plan` (`main.py:146`) | Create plan, enqueue job. |
| `GET /api/plans` / `/{id}` | operator | — | List / detail. |
| `GET /api/plans/{id}/stream` | operator (token in query) | `plan_sse_stream` (`main.py:42`) | SSE progress every 0.5 s, keepalive every 15 s. |
| `POST /api/plans/{id}/approve` | expert | `approve` (`main.py:222`) | Guarded by state machine + `needs_revalidation`. |
| `PATCH /api/plans/{id}/setpoints` | expert | `edit_setpoints` (`main.py:287`) | Set `needs_revalidation`, clear predicted KPIs. |
| `POST /api/plans/{id}/deploy` | expert | `deploy_plan` (`main.py:268`) | Set `DEPLOYING` before enqueue (idempotent). |
| `GET /api/live`, `/stream`, `/series` | operator | telemetry | Live frame, SSE, time-series. |
| `POST /api/telemetry` | operator | `post_telemetry` (`main.py:414`) | Real-historian push seam. |
| `GET /api/topology` | operator | `build_hall_topology` (`topology.py:224`) | 3D scene layout. |

**JobRunner & SSE.** `JobRunner` (`jobs.py:25`) is a single-worker thread queue. `run_plan_job` (`jobs.py:142`) builds the oracle/forecaster/calibration, runs `run_weekly_plan`, writes `recommendation.json` + `progress.json`, then runs prevalidation. `run_deploy_job` (`jobs.py:344`) runs the perturbed plant, persists realized KPIs, advances history/calibration. Cancellation is cooperative (`progress_cb` raises `PlanCancelled`); orphans are reconciled to terminal on startup.

**Status state machine** (`status.py`): `queued → running → {pending_approval | infeasible_fallback | blocked_unsafe | failed | cancelled}`; `pending_approval → {approved | rejected}`; `blocked_unsafe`/`infeasible_fallback → rejected only`; `approved → {deploying | rejected}`; `deploying → {deployed | deploy_blocked | deploy_failed}`. `can_transition` (`status.py:35`) gates every change.

**Frontend pages** (`src/frontend/src/pages/`): **Login**, **Dashboard** (latest plan + KPIs), **NewPlan** (form + live SSE progress, 5× reconnect), **Review** (setpoints, predicted KPIs, baseline, robust bands, trajectory, expert actions), **Live** (22-rack heat-map, alerts at ≥25/≥26 °C, compliance ±0.5/axis, 30-min chart, SSE + poll fallback), **History** (sortable/filterable table), **DigitalTwin3D** (three.js hall + animated airflow, live rack-row coloring). The API client is `src/api.ts`; EventSource URLs carry the token in the query (`planStreamUrl`, `api.ts:112`) since EventSource cannot set headers.

**Run / build / test commands.**

```bash
# whole app, single origin
scripts/clear-and-run.sh

# frontend dev (hot reload, proxies /api → :8000)
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run dev
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build   # tsc -b && vite build
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test        # vitest
```

**Notable gotchas.** Progress writes are atomic (`os.replace`); non-finite floats are replaced with `null` before JSON serialization; deploy is idempotent (status set to `DEPLOYING` before enqueue, `run_deploy_sync` skips already-deployed); the inlet 26 °C cap is a 0-tolerance deploy gate.

---

## Experimental results

The repo captures **6 consecutive weekly cycles** (2024-11-08 → 2024-12-13) under `src/runs/gds-2024-MM-DD-HASH/`.

**Run-directory layout.**

| File / folder | Contents |
|---|---|
| `recommendation.json` (schema 1.7–1.8) | Setpoints, `predicted_kpis`, `baseline`, `robust` (confidence bands p50/p90/max, scenario diagnostics), `status`, `k_sigma`, `inlet_forecast_margin`, `energy_scope`. |
| `realized.json` (schema 1.8) | Measured `total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max_c`, `inlet_violation_steps`. |
| `progress.json` | Search checkpoint (level, evals, best score). |
| `oracle/cand-XXXX/.../eplusout.csv` | Per-candidate full-week EnergyPlus output (6 MB+, 15-min timeseries). |
| `robust/scenario-00…03/` | Robust re-sims (4 perturbed plants + hot-weather), each with `plant.idf` + `oracle/`. |
| `prevalidation/` | `report.md`, `trajectory_ai.csv`, `trajectory_worst.csv`. |
| `deploy/oracle/` | Deployed-week run (ground truth for calibration); `bms_commands.json` records the 45 shadow commands. |
| `plant/` | Physics model snapshot (`plant.idf`, `plant.prototxt`) frozen at deploy time. |

**Where the numbers live.** Predicted energy: `recommendation.json → predicted_kpis`. Realized energy/inlet: `realized.json`. Savings: `energy_reduction_vs_baseline_pct`. Safety: `realized.json → inlet_temp_max_c` / `inlet_violation_steps`. Calibration σ: `recommendation.json` calibration fields.

**Figures** (`dctwin/BHUMANS/deck_assets/`, generated by `make_deck_full.py`):

| Figure | Shows |
|---|---|
| `figA_accuracy.png` | Predicted vs realized energy across 6 weeks; prediction error shrinking. |
| `figB_savings.png` | Energy savings ramp (0 % → ~3.6 %) correlated to uncertainty σ dropping (1.0 °C → ~0.43 °C). |
| `figC_safety.png` | Realized peak inlet (23.37 → 25.60 °C) vs the 26 °C hard cap; 0 violations. |
| `figD_safety_stack.png` | The three-net safety mechanism + safety-ladder substitution. |
| `figE_dataflow.png` | Closing-the-loop dataflow (shadow BMS, telemetry, live dashboard, field seams). |
| `figF_procedure.png` | The 6-step operator weekly procedure. |

The headline measured results and forensic findings are summarized in `dctwin/BHUMANS/review_after_4th_draft.md` (§2.4) and the dated findings under `docs/superpowers/specs/`.

> **Caveat (important for citing results).** Realized KPIs come from the **perturbed-plant EnergyPlus simulation**, not real field telemetry — the loop is *structurally* closed, but "reality" is still a physics simulation. Recirculation is currently **inert** (the `AdjustedSupply` blend sees zone air ≈ supply temp), so inlet is driven by SAT + flow-dependent fan heat; this makes the safety margin optimistic versus a real hall with imperfect containment. Always check `recommendation.json` schema is ≥ 1.7 before comparing baseline/savings fields.

---

## Extending DCTwin (developers)

DCTwin follows a strict workflow: **brainstorm → spec (`docs/superpowers/specs/`) → plan (`docs/superpowers/plans/`) → adversarial verification → subagent build → merge (`--no-ff`) → graphify update.** Plans are written **test-first**; never weaken an assertion to make code pass.

### Recipe: add a new objective

The objective is hard-coded in `score()` (`objective.py:47`), not a callback. Either (a) modify `score()` to add/replace a term, or (b) have the oracle set a different `energy_term` on the `WeeklyKPI` (the tariff path is the canonical example — `weighted_energy_cost` replaces raw energy when `data/tariff.json` exists). Bump the schema version if the recommendation shape changes.

### Recipe: change the search space

`DEFAULT_SEARCH_SPACE` (`types.py:81`) is the single source of truth. There is no JSON config for bounds — construct a custom `SearchSpace` and pass it to `BeamPlanner.__init__`. Per-actuator bounds can come from the live env via `mapper_from_env`. If you change the 45-actuator order, update `gds_action_spec` (`broadcast.py:59`) **and** the prototxt declaration **and** `expand_commands` in `bms.py` — they must agree.

### Recipe: add a constraint

Add a hard check to `is_feasible()` (`objective.py:35`) and/or a soft penalty term to `score()`. Soft-penalty accumulators must be **computed by the oracle** (`aggregate_kpi`, `kpi.py:50`) and attached to `WeeklyKPI` (`types.py:49`) — the objective only sums them. Respect the conjunctive hard gate and the 26 °C invariant.

### Recipe: plug a real BMS

Implement `BacnetBmsAdapter.apply` (`bms.py:73`) with the same contract as `ShadowBmsAdapter` but `actuated:true`. Wire it through `bms_adapter_for_mode` (`jobs.py:331`) behind a new `DTWIN_DEPLOY_MODE` value. Verify the 45-command order matches `gds_action_spec` and the prototxt.

### Recipe: add an API route / frontend page

Backend: add the route in `webapp/main.py`, guard it with the appropriate role via `TokenAuth`, and respect the status state machine (`can_transition`). Frontend: add a page under `src/frontend/src/pages/`, a client call in `src/api.ts`, and a nav entry in `App.tsx`. The build (`tsc -b`) type-checks test files with `noUnusedLocals` ON — drop unused imports or the build fails (TS6133).

### Run the tests

```bash
# fast unit tests (EnergyPlus mocked via MockEvaluator)
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -q

# Docker-gated integration tests (real EnergyPlus; slow, flaky on BCVTB — wrap in a hard timeout)
sg docker -c "env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src PYTHONPATH=\$PWD \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -m integration -q"

# frontend
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test
```

`pyproject.toml` sets `addopts = "-q -m 'not integration'"`, so Docker tests are deselected by default. Rely on the exit code + `N passed` count (the summary is often buried under warnings).

### Key invariants you must not break

- **Inlet ≤ 26 °C at every step** — enforced in search (net 1), scenarios (net 2), and deploy backstop. Never relax it to make a search succeed.
- **Process-based parallelism** — the dctwin config is a process-global singleton; never assume thread-safety for config-dependent state.
- **No double-hedging** — scenarios clear `inlet_forecast_margin` (`robust.py:201`); don't stack net-1's k·σ inside net-2.
- **Schema is versioned and additive** — bump on shape changes (`1.0 → 1.7 → 1.8`), keep older readers working.
- **Residuals fit against raw predictions** — `residual_predicted_for` prevents double-correction.
- **Don't weaken tests** — implementers make code pass; never relax an assertion.
- After merging code, **regenerate `graphify-out/`**. Do **not** push to `origin` without explicit go-ahead.

---

## Glossary & key conventions

| Term | Meaning |
|---|---|
| **SAT** | CRAH supply-air temperature setpoint (°C), bounds [20, 26]. |
| **Flow / airflow** | CRAH supply-air mass flow per ACU (kg/s), bounds [4.8, 13.8]. |
| **CHWST** | Chilled-water supply temperature (°C), bounds [13, 19]. |
| **Oracle** | The full-week EnergyPlus-in-Docker evaluator (`ParallelEnvOracle`) that scores each candidate. |
| **Broadcast** | Expansion of the 3 global setpoints to the 45-actuator `[22 SAT, 22 FLOW, 1 CHWST]` normalized action vector. |
| **`energy_scope`** | Label (`"hall_controllable_v1"`) for the HVAC energy metric: the 1F-2A ACU fans + shared chiller/CHW plant — **not** facility total−IT (which is the legacy fallback only when component powers aren't discovered). |
| **WeeklyKPI** | The aggregated 1-week outcome (energy, PUE, inlet max, violations, soft penalties, optional weighted cost). |
| **Three nets** | The layered safety gate: k·σ pre-tightening, robust ensemble, safety-ladder deploy backstop. |
| **Shadow mode** | Deployment that writes 45 BMS commands to disk but never actuates; realized KPIs still come from the oracle. |
| **Schema versioning** | `recommendation.json` versions: 1.0 → 1.5 (adds time-block `schedule`) → 1.7 (adds as-operated `baseline` + `energy_scope`) → 1.8 (adds `deploy_mode`/`bms`/`realized_source`). |
| **`mock_evaluator`** | The fast analytic stand-in for EnergyPlus used by **all** unit tests — never invoke real EnergyPlus from a unit test. |
| **Degenerate / no-signal** | Coarse grid with < 0.1 °C inlet spread and < 1 % energy spread → control-invariant model, flagged for review. |

---

## Reference map

| Concern | Primary file(s):line |
|---|---|
| Beam search algorithm | `src/planner/beam_search.py:85` (`plan`), `:33` (`BeamConfig`), `:60` (`_coarse_grid`), `:174` (`_neighborhood`) |
| Objective & feasibility | `src/planner/objective.py:47` (`score`), `:35` (`is_feasible`), `:12` (`ObjectiveWeights`) |
| Setpoint / search-space types | `src/planner/types.py:8` (`Setpoints`), `:35` (`SearchSpace`), `:81` (`DEFAULT_SEARCH_SPACE`), `:49` (`WeeklyKPI`) |
| Pipeline orchestration | `src/planner/pipeline.py:62` (`run_weekly_plan`), `:19` (`apply_forecast_margin`) |
| EnergyPlus oracle | `src/planner/oracle.py:107` (`evaluate`), `:19` (`OracleConfig`); `src/planner/oracle_worker.py:168` (`evaluate_one`) |
| KPI aggregation / monitor | `src/planner/kpi.py:50` (`aggregate_kpi`); `src/planner/monitor.py:35` (`discover_monitor`) |
| EnergyPlus / BCVTB / Docker | `dctwin/registration.py:9` (`make_env`); `dctwin/third_parties/eplus/core.py:23`; `dctwin/third_parties/docker_backend.py:14` |
| Mock evaluator (tests) | `src/planner/mock_evaluator.py:24` |
| Broadcast (3 → 45) | `src/planner/broadcast.py:46` (`expand`), `:59` (`gds_action_spec`) |
| Time-block scheduling | `src/planner/schedule.py:32`; `src/planner/schedule_search.py:35` (`refine_schedule`) |
| Robust "three-net" gate | `src/planner/robust.py:173` (`make_oracle_robust_rerank`), `:132` (`robust_select`), `:64` (`safety_ladder`), `:44` (`scenario_spread`) |
| Plant perturbation | `src/planner/plant.py:21` (`PlantConfig`), `:28` (`DEFAULT_PLANT`), `:58` (`apply_perturbation`) |
| Pre-validation | `src/prevalidation.py:68` (`run_prevalidation_with_oracle`); `src/planner/validation.py:7` (`validation_metrics`) |
| Deploy + BMS seam | `src/deploy.py:28` (`deploy`); `src/planner/bms.py:52` (`ShadowBmsAdapter.apply`), `:73` (`BacnetBmsAdapter`) |
| Calibration | `src/planner/calibrator.py:81` (`fit_calibration`), `:43` (`apply`), `:122` (`recompute_calibration`) |
| Physics recalibration | `src/planner/recalibrator.py:23` (`fit_plant_factors`), `:48` (`recalibrate`) |
| As-operated baseline | `src/planner/baseline.py:41` (`as_operated_setpoints`); `src/planner/recommendation.py:11` (`energy_reduction_pct`) |
| Loop closure / history | `src/planner/history.py:16` (`advance_history`), `:46` (`advance_calibration`) |
| IT-load forecaster | `src/planner/forecaster.py:134` (`StatisticalForecaster`), `:167` (`SeasonalForecaster`), `:208` (`build_forecaster`) |
| Weather forecaster | `src/planner/weather_forecast.py:33` (`weather_stats`), `:95` (`weather_scenarios`); `src/planner/epw.py:50` (`week_within_epw`) |
| Forecaster fit / backtest | `src/fit_forecaster.py:42` (`main`); `src/planner/backtest_forecaster.py:31` |
| Week config (prototxt) | `src/planner/week_config.py:32` (`write_week_config`) |
| Live telemetry / recirc | `src/webapp/telemetry.py:48` (`TelemetryStore`), `:126` (`SimTelemetryFeed`); `src/planner/recirc.py:81` (`RecircAwareEvaluator`); `src/fit_recirc.py:75` |
| Web backend | `src/webapp/main.py:102` (`create_app`), `:42` (`plan_sse_stream`); `src/webapp/jobs.py:25` (`JobRunner`), `:142` (`run_plan_job`), `:344` (`run_deploy_job`) |
| Auth / status / store | `src/webapp/auth.py:11` (`TokenAuth`); `src/webapp/status.py:35` (`can_transition`); `src/webapp/store.py:31` (`PlanStore`) |
| Frontend shell / client | `src/frontend/src/App.tsx:23`; `src/frontend/src/api.ts` |
| Frontend pages | `src/frontend/src/pages/{Login,Dashboard,NewPlan,Review,Live,History,DigitalTwin3D}.tsx` |
| 3D topology / scene | `src/webapp/topology.py:224` (`build_hall_topology`); `src/frontend/src/three/HallScene.tsx:61` |
| Result artifacts | `src/runs/gds-2024-MM-DD-HASH/{recommendation,realized,progress}.json`, `oracle/`, `robust/`, `prevalidation/`, `deploy/`, `plant/` |
| Report figures | `dctwin/BHUMANS/deck_assets/fig{A,B,C,D,E,F}.png`; `dctwin/BHUMANS/make_deck_full.py` |
