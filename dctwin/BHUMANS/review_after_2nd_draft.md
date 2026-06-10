# Review: Digital Twin Dual-Loop Control Framework — After 2nd Draft

**Date:** 2026-06-07
**Scope:** Review the 2nd-draft framework against the original design spec
(`docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md`), the closing-fidelity-loop
and forecast-realism specs, and the workflow in `/mnt/lv/home/hoanghuy/newcode/optimization-plan.jpg`.
**Method:** ran `/graphify` on `src/` (1041 nodes · 1897 edges · 83 communities), then a 14-agent
file-grounded audit (7 subsystem auditors → adversarial verifiers → completeness critic + live test run);
the three highest-stakes findings were re-verified by hand against code + persisted run artifacts.
**Objective being assessed against:** a Digital Twin deployment for **weekly operation** with
**high-fidelity recommendations**.

---

## One-line verdict

The 2nd draft **wired up everything the 1st-draft review asked for** — the deploy endpoint, calibration,
robust scenario selection, the perturbed plant, and forecast realism (FA/FB) — and the suite is green
(**172 backend + 57 frontend tests pass**; 6 Docker integration tests deselected by default). But turning
on the perturbed plant **exposed a demonstrated safety/fidelity failure that the framework neither catches
nor recovers from**, and the *forecaster* feedback loop is still not closed (the *calibration* loop is).
The engineering is sound; the **fidelity objective is now measurably unmet** — which is real progress,
because the gap is finally observable in a persisted artifact rather than hypothetical.

What changed since the 1st draft: 1st draft = inner loop ✅ + outer loop to the expert gate. 2nd draft adds
**P1** (deploy endpoint + status state machine), **P2a** (calibration + uncertainty), **P2b** (robust
re-rank), **P2c** (recalibrator no-op seam), **FA** (seasonal forecaster + bands), **FB** (real-weather EPW).

---

## 1. How does graphify help the next development?

The graph (`graphify-out/GRAPH_REPORT.md`) is most useful in four concrete ways:

- **Blast-radius map for safe changes.** God nodes are `Setpoints` (67 edges), `ObjectiveWeights` (45),
  `WeeklyKPI` (38). The two most valuable fixes below (carry *raw* predicted KPIs; add forecast bands to the
  contract) both mutate `WeeklyKPI` / `recommendation.json` — they ripple across ~38 edges and every test
  community (20, 29, 39, 50). Graphify says up front: treat those as cross-cutting migrations, not local edits.
- **Orphan detection — structurally.** The "History Advance / loop closure" community (21) sits as a
  near-leaf *instead of* feeding the "Load Forecaster" community (7). That topology **is** the open forecaster
  loop, visible without reading a line. `Path` is a 0.251-betweenness bridge across 17 communities → filesystem
  coupling is the integration glue, consistent with the orphaned `report.md` / `trajectory_*.csv` artifacts that
  have no real handoff.
- **"What the graph believes vs. what the code does."** Graphify *inferred* a "Weekly dual-loop control
  pipeline" hyperedge (forecaster→…→deploy→recommendation) — but the code does **not** wire it (pre-validation
  never calls the replay; refit is never called). Where graph-inferred edges and real call edges diverge is a
  high-signal place to find unwired components. (Caveat: 33% of edges are INFERRED, avg conf 0.75; the 225
  isolated nodes are mostly TS-config noise.)
- **Onboarding + `graphify query`.** A new developer navigates by community ("Beam Search Planner", "KPI &
  Oracle Worker", "Robust Scenario Selection") and traces any path on demand instead of grepping cold.

---

## 2. Implemented / not implemented / why / issues

### ✅ Implemented and verified (`done`)

| Area | Evidence |
|---|---|
| **Inner loop** — best-first coarse-to-fine beam search over the constant 3-setpoint trio; 3→45 broadcast (order-safe, derived from the live env, not the hardcoded helper); hard inlet≤26 °C filter before beam admission; energy-dominant objective + soft penalties; MockEvaluator TDD | `planner/beam_search.py`, `broadcast.py`, `objective.py:33-52` |
| **Oracle seam** — clean `Evaluator` protocol (planner never imports E+); genuine process-based parallelism (dctwin `config` is a process-global singleton); absolute LOG_DIR → Docker volume; hall-scoped thermal KPIs | `planner/oracle.py`, `oracle_worker.py`, `kpi.py` |
| **Outer-loop wiring (P1)** — `POST /api/plans/{id}/deploy` (expert-gated); validated status state machine; perturbed plant (fan ×0.93 / coil flow ×0.85 via opyplus) | `webapp/main.py:89-100`, `status.py`, `plant.py:24-46` |
| **Calibration + robustness (P2a/b/c)** — per-KPI bias/σ applied before scoring (incl. inlet→feasibility gate); robust_select (worst-case feasibility across scenarios + CVaR energy + p50/p90 bands); recommendation schema 1.1; recalibrator no-op seam | `calibrator.py`, `robust.py:68-91`, `recalibrator.py` |
| **Forecast realism (FA/FB)** — SeasonalForecaster (weekday×ToD climatology + p10/p50/p90 bands); `build_forecaster` factory; honest backtest; real-weather EPW seam | `forecaster.py`, `backtest_forecaster.py`, `epw.py` |
| **Webapp** — 5 React views; token auth; background JobRunner; SQLite+file store; topology; calibration panel; confidence bands; realized-vs-predicted on Review | `webapp/`, `frontend/src/pages/` |

### 🟡 Partial / diverges from spec

- **Forecaster sub-loop is NOT closed.** Realized KPIs land in a *separate* `data/realized_history.csv` that no
  forecaster path reads; `refit_from_history` has **zero callers** and would re-read the unchanged fit CSV anyway.
  The **calibration** sub-loop *is* closed (realized → `calibration.json` → next objective) — arguably the more
  important feedback — but the spec §9 "realized System Data feeds the next week's forecaster" claim is unmet.
- **Real-weather seam built but disabled in the shipped artifact** — `models/forecaster.pkl` has
  `weather_file=None, method="persistence"`, so production runs static IWEC weather. (Persistence-as-default is
  *correct* given the flat-telemetry backtest; the weather disable is incidental and should be re-enabled.)
- **Pre-validation is not an independent replay** — `prevalidation.py:38` reads `predicted_kpis` straight from
  JSON for the "AI" side and only re-runs the oracle for the baseline; `ai_trajectory_test.py:36` replays with
  `policy="baseline"` (likely a bug). The expert gate reviews the planner's *own prediction*, not a check.
- **Webapp API drift** — progress is HTTP polling, not the spec's WebSocket; `GET /trajectory` is absent;
  Review has no per-step inlet/power/PUE plots; History has no predicted-vs-realized trend chart; the 3D view
  only type-checks/bundles (never rendered on a real GPU — the test mocks the WebGL boundary).
- **§11 startup fail-fast validation mostly missing** (no broadcast-dim==45 / budget>0 / weights≥0 gate before
  launching ~245 EnergyPlus runs).

### ❌ Not implemented — and why

- **Real telemetry / true twin-vs-reality calibration, time-varying & per-hall setpoints, ML forecaster, real
  BMS adapter** — all **deliberate v1 non-goals / locked decisions** (spec §2–3, §15). Not oversights.
- **FC (load-uncertainty scenarios)** — deferred: GDS telemetry is ultra-flat (~0.06–0.1% utilization), so load
  bands aren't trustworthy (backtest PICP ~0.16 vs 0.80 target). Reasonable.
- **Equipment on/off twin outputs (§4.3)** — genuine gap, not a stated non-goal.

### 🔴 Verified issues (by severity)

**HIGH — the fidelity story:**

1. **Demonstrated safety breach under model mismatch.** The repo's only realized artifact: the planner predicted
   SAT 20 / flow 7.05 / CHWST 13 → **28,595 kWh, peak 25.79 °C, 0 violations**
   (`runs/gds-2013-11-11-demo/recommendation.json`); deployed to the perturbed plant it realized **370,554 kWh
   (13×), peak 29.98 °C, and 666 of 672 steps over the 26 °C cap** (`runs/gds-2013-11-11-demo/realized.json`).
   The twin==plant assumption is *what makes predicted≈realized*; the moment the plant differs, a "0-violation"
   plan runs ~4 °C hot for 99% of the week — and nothing in the pipeline catches it (robust re-rank doesn't gate
   the deploy). NB: this is the perturbed-plant deploy that P2a/P2b deliberately introduced as a realism stress
   test — M7's 0-violation result still holds in the twin==plant regime; the point is that under a *plausible*
   degraded plant the framework neither gates against the breach nor recovers from it.
2. **The gate that should catch it can't** — pre-validation echoes predicted KPIs (above), so an expert
   approving this plan sees "0 violations."
3. **Calibration self-poisons.** `data/calibration.json`: inlet bias **+4.19 °C, σ=0, n_weeks=1** — a single
   deploy with no σ-prior / outlier-clip would flip every candidate infeasible next week. Compounded by
   double-correction (calibration is fit against already-calibrated predictions; `beam_search.py:139-141`).
4. **`PATCH /setpoints` is doubly unsafe** — keeps **stale `predicted_kpis`** *and* has **no status gate**
   (setpoints mutable after approval, then deployable; `webapp/main.py:102-109`). Auth also **fails open** when
   no tokens are configured (everyone becomes expert).

**MEDIUM:** robust re-rank has no scenario error-handling (one failed scenario crashes the whole plan); worker
`env.close()` doesn't tear down the E+ container / BCVTB socket (leak); an empty hall-scoped monitor silently
defeats the inlet safety KPI; cross-year EPW rejection blocks valid within-coverage Dec→Jan weeks; no
compute/cost guard on the ~245-run budget.

**LOW:** recommendation still labels weather `"TMY-window"` even on real-EPW runs; day-of-week not aligned (real
Monday simulated as Tuesday — ~nil impact, no weekday-keyed schedules); hour-of-day fallback tier in
`seasonal_climatology` has no min_samples guard; hvac energy can go negative on a single noisy step (no clamp);
hardcoded pseudo-baseline in the Review KPI comparison; misleading "Twin Live" label on planned-state HUD.

### Test status (verified live)

- **Backend:** `172 passed, 6 deselected` under `.venv-dtwin/bin/python -m pytest` from `src/` (the miniconda
  py3.13 interpreter lacks `dctwin` and fails collection — must use the venv). Suite is green.
- **Integration:** the 6 deselected are exactly the Docker-gated `tests/integration/` set
  (deploy_loop=1, oracle_eplus=2, plan_weekly=1, real_weather=1, robust_rerank=1).
- **Frontend:** `57 passed` across 8 vitest files; `npm run build` clean.

---

## 3. Suggested next steps

**NOW — close the fidelity/safety gap (decisive for the objective):**

1. **Gate deploy on robust-feasibility** (or add a pre-deploy re-check on the deploy plant) so a plan that
   breaches under any perturbed scenario can't reach `approved` → directly prevents the 666-violation deployment.
2. **Make pre-validation a real independent replay**, emit `report.md` + `trajectory_*.csv` into `runs/<id>/`,
   and fix the `policy="ai"` slot.
3. **Stop calibration self-poison** — persist *raw* uncalibrated `predicted_kpis` for residual fitting; add the
   §6.1 σ-prior + outlier clip so n=1 doesn't yield σ=0 / +4.19 °C bias.
4. **Re-run and publish M7 acceptance on the perturbed plant with *realized* numbers** — until a realized (not
   predicted) 0-violation week exists, the "high-fidelity, 0 violations" headline is unsupported.
5. **Webapp safety trio:** status-gate `PATCH /setpoints` + null its stale KPIs on edit; make auth fail-closed.

**NEXT:** wire `GET /trajectory` + per-step inlet/power/PUE plots + History predicted-vs-realized trend (so the
breach is *visible*); add the §11 startup fail-fast gate; carry forecast bands into the safety margin (schema
1.2) and re-enable the real-weather pkl; robust scenario error-handling + container-kill on timeout.

**LATER (clean §15 seams, after fidelity is closed):** close the forecaster sub-loop or explicitly document
calibration as the chosen feedback path; equipment on/off twin outputs; real BMS adapter; per-hall / time-block
setpoints; ML forecaster.

---

## 4. How does the webapp help operators (weekly-operation objective)?

The webapp turns a multi-step researcher pipeline (fit forecaster → run hundreds of EnergyPlus sims → score →
build recommendation → validate) into a **weekly operator cockpit** matching the Monday-replan cadence:

- **New Plan** — operator launches the weekly plan (week_start + search params) and watches **live progress**
  (level / evals / best-score). The "run the program on Monday" action, no CLI.
- **Dashboard** — at-a-glance current-week **recommended 3 setpoints + predicted KPIs + status badge + headline
  energy reduction**.
- **Review & Approve** (the human-in-the-loop gate) — KPI-vs-baseline table, **confidence bands** (p50/p90/max +
  robust-feasible flag), a **twin-calibration panel** (how far the twin has historically over/under-predicted),
  an **expert setpoint editor**, and **approve / reject / deploy**. This is "Expert Supervision" from the diagram.
- **History** — past plans, sortable, deep-linked to Review; per-plan realized-vs-predicted after deploy.
- **Digital Twin (3D)** — schematic of the 1F-2A hall (22 CRAHs, cold/hot aisles, plant) with **airflow particles
  whose speed ∝ recommended airflow and color ∝ SAT→inlet**, so an operator can *see* what a setpoint change does.

**Honest limits for the high-fidelity objective:**

- Everything displayed is **planned / forecast / post-hoc-realized — never live plant telemetry** (the 3D "Twin
  Live" chip is misleading), so an operator can't see reality drift before approving.
- **The review doesn't surface the safety risk:** no per-step inlet trajectory, and pre-validation just re-shows
  the planner's predicted KPIs — so an operator approving the demo plan would read "0 violations" while the
  realized run breached for 99% of the week.
- The Review baseline is a **hardcoded pseudo-baseline**, so displayed % savings are illustrative, not
  plan-specific.
- The 3D view has never been verified on a real GPU, and there's **no login/role UI** (bearer token hand-seeded
  into `localStorage`).

**Bottom line:** the webapp is already a genuine operator/expert shell supporting the weekly
trigger→review→approve→deploy workflow end-to-end. To make it help operators produce *high-fidelity, safe*
recommendations, the three NOW items — independent pre-validation surfaced in Review, per-step inlet plots, and
robust-feasibility deploy gating — convert it from "a recommendation viewer" into "a safety-checked decision tool."

---

## Appendix — evidence index (file:line)

- Demonstrated breach: `runs/gds-2013-11-11-demo/recommendation.json` (predicted 0 viol) vs `realized.json`
  (666/672 viol, 13× energy, peak 29.98 °C).
- Calibration poison: `data/calibration.json` (inlet bias +4.19 °C, σ=0, n_weeks=1).
- Pre-validation not a replay: `prevalidation.py:20-26,38`; AI replay uses baseline policy: `ai_trajectory_test.py:36`.
- PATCH unsafe: `webapp/main.py:102-109` (stale KPIs, no status gate).
- Forecaster loop open: `planner/history.py:32-40` (refit zero callers), `fit_forecaster.py:42-47` (unchanged CSV),
  `webapp/jobs.py:157-203` (run_deploy_job never calls refit).
- Real-weather disabled in prod: `models/forecaster.pkl` (`weather_file=None`, `method="persistence"`).
- Robust no error-handling: `planner/robust.py:108-121`. Container leak: `oracle_worker.py:97`.
- §11 fail-fast missing: `plan_weekly.py:30-66` (only grid≥2, Bounds lb≤ub, year-wrap reject implemented).
- Inner loop solid: `beam_search.py:64-168`, `objective.py:33-52`, `broadcast.py:46-56`, `env_actions.py:49-52`.
