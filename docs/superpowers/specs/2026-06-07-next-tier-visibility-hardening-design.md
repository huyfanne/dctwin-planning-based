# NEXT Tier — Visibility + Hardening — Design Spec

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope tier:** the **NEXT** items from the 2nd-draft review
  (`dctwin/dctwin/BHUMANS/review_after_2nd_draft.md` §3) + this design's clarifications
- **Predecessor spec (NOW tier, merged):** `2026-06-07-close-fidelity-safety-gap-design.md`

---

## 1. Context & problem statement

The NOW tier closed the fidelity/safety gap: a plan that would breach the 26 °C inlet cap on the
perturbed plant can no longer be approved or silently deployed. But the operator still cannot **see**
the breach risk, the engine has no startup guard against misconfiguration, production runs on static
TMY weather (the real-EPW seam is built but disabled in the persisted forecaster), and a single failed
robust scenario or a hung EnergyPlus container can take down a plan.

**Theme:** make the safety state **visible to operators before they approve**, and make the engine
**robust to misconfiguration, real weather, and scenario failures.**

**Discovery during design:** the NOW tier added `replay_with_trajectory` only to `MockEvaluator` (for
tests). The production `ParallelEnvOracle` has no trajectory capture, so `run_prevalidation` currently
emits **no** trajectory CSV in production (`prevalidation.py` falls to the `rows=[]` branch). Making the
real oracle capture per-step samples is part of this tier.

## 2. Goals / non-goals

**Goals**
- Operator sees the recommended plan's **per-step inlet/power/PUE trajectory** on both the nominal twin
  and the **worst-case perturbed scenario**, with the 26 °C cap drawn — at plan time, before approval.
- History shows a **predicted-vs-realized energy trend** across deployed weeks.
- A **startup fail-fast** rejects a misconfigured plan before launching hundreds of EnergyPlus runs.
- Production runs on **real EPW weather**; `recommendation.json` reports the **honest** weather source +
  forecast bands (schema 1.3).
- The robust re-rank **survives a failed scenario**; a hung/timed-out EnergyPlus container is **torn down**.

**Non-goals (deferred to LATER)**
- §6.5 k·σ inner-search inlet pre-tightening (search-time breach avoidance).
- FC active load-scenario joint robustness (the forecast-margin hook ships **off**).
- Real BMS adapter; per-hall / time-block setpoints; ML forecaster; forecaster sub-loop closure.
- WebSocket progress (the existing GET-poll stays).

## 3. Decisions locked during brainstorming

| Question | Decision |
|---|---|
| Scope | All 4 NEXT items in one spec (visibility + 3 hardening items). |
| Review trajectory | **Nominal + worst-case scenario** overlay — see the breach risk *before* approving. |
| "Worst-case" plant | The deterministic **max-perturbation** (hottest) scenario — `make_scenarios(...)[0]` (smallest multiplier → most-degraded → hottest; DEFAULT_PLANT factors are <1), not threaded from the rerank — simpler + reproducible. |
| Item 3 forecast | Re-enable real-weather pkl + honest labels/bands (schema 1.3) + a **forecast-margin hook that defaults OFF** (no-op on flat data). |

## 4. Component design

### 4.1 Trajectory visibility (item 1)

**A1 — real per-step capture** (`planner/oracle.py`, `planner/oracle_worker.py`). Add
`ParallelEnvOracle.replay_with_trajectory(setpoints, forecast) -> (WeeklyKPI, list[StepSample])`: an
inline single-candidate run (no process pool) using a sample-returning variant of `run_episode`
(`run_episode_with_samples`) that returns both the aggregated `WeeklyKPI` and the per-step
`list[StepSample]`. Mirrors the existing `MockEvaluator.replay_with_trajectory` signature so
`prevalidation` treats them interchangeably.

**A2 — pre-validation replays two plants** (`prevalidation.py`). `run_prevalidation` gains an optional
`worst_evaluator`. When provided, it also replays the recommended setpoints on it and writes
`trajectory_worst.csv` alongside `trajectory_ai.csv` (both via `step_trajectory` + `write_trajectory_csv`).
`run_prevalidation_with_oracle` builds the worst-case oracle deterministically: the max-perturbation plant
`make_scenarios(DEFAULT_PLANT, n_scenarios, scenario_spread(load_calibration()))[0]` (hottest/most-degraded) →
`build_plant_prototxt` → a 1-worker `ParallelEnvOracle`. So `runs/<id>/prevalidation/` holds both CSVs.

**A3 — backend** (`webapp/main.py`, `webapp/store.py`).
- `GET /api/plans/{id}/trajectory` (operator) → `{"nominal": [...rows...], "worst": [...rows...]}`,
  each row `{step, inlet_temp_max_c, hvac_power_kw, pue}`. Reads the two CSVs from the plan dir via a
  `store.get_trajectory(plan_id)` helper; missing CSV → that key is `[]` (200, not 404).
- `realized_energy_kwh` column added to the SQLite `plans` table; set in `save_realized` (from the
  realized KPIs). `list_plans` returns it; `PlanSummary` gains `realized_energy_kwh`.

**A3 — frontend** (`frontend/src/api.ts`, `pages/Review.tsx`, `pages/History.tsx`).
- `api.ts`: `getTrajectory(id) -> { nominal: TrajRow[]; worst: TrajRow[] }`; `PlanSummary.realized_energy_kwh`.
- Review: a **Trajectory** card with a Recharts `LineChart` — inlet (nominal cyan, worst red) + a dashed
  `ReferenceLine y=26` cap; smaller power-kW and PUE line charts below. Loads via `getTrajectory` when a
  plan is selected; hidden if both series are empty.
- History: a **predicted-vs-realized energy trend** `LineChart` above the table (x = week_start;
  predicted `energy_kwh` cyan, `realized_energy_kwh` amber for deployed plans).

### 4.2 Startup fail-fast (item 2)

`planner/pipeline.py` gains `validate_plan_request(request, weights, beam)` called at the **top of
`run_weekly_plan`**, before the forecast/search. Checks (raise `ValueError` with a specific message):
`beam.grid >= 2`, `beam.beam_width >= 1`, `beam.levels >= 0`, `beam.max_evals > 0`, `request.days >= 1`,
and every `ObjectiveWeights` field `>= 0`. Separately, a broadcast-dim assertion in the oracle path
(`mapper_from_env`): the expanded action vector length equals the env's `AGENT_CONTROLLED` action count;
mismatch raises before any episode. `webapp/main.py::create_plan` catches `ValueError` → HTTP 422.

### 4.3 Forecast realism (item 3)

- **Re-enable weather:** regenerate `models/forecaster.pkl` via `fit_forecaster` with
  `--weather data/weather/Singapore_Changi_Nov2024-Jan2025.epw` so the persisted pkl carries
  `weather_file` (the threading already exists; only the artifact is stale). Documented command in the plan.
- **Honest labels (schema 1.3):** `build_recommendation` gains `forecast_meta: dict` and replaces the
  hardcoded `{"method":..., "weather":"TMY-window"}` with the real `{"method", "weather", "bands"}` where
  `weather` is the EPW basename when a real weather file is set, else `"TMY-window"`. Pipeline passes
  `forecast.weather_file` + `forecast.method` + `forecast.bands`. Bumps `schema_version` to **1.3**.
- **Ready-but-off margin hook:** `ObjectiveWeights` gains `inlet_forecast_margin: float = 0.0` (°C). When
  `> 0`, `objective.is_feasible` tightens the **feasibility gate**: a candidate is rejected when
  `kpi.inlet_temp_max + inlet_forecast_margin > inlet_cap` (in addition to the existing
  `inlet_violation_steps` check) — a pre-tighten on the hard cap using data `is_feasible` already has.
  Default `0.0` → byte-for-byte current behavior. Documented as the activation point when load variance
  grows; not wired to any auto-computed value this tier. (The `inlet_cap` is passed to `is_feasible`,
  defaulting to the `OracleSettings` 26 °C.)

### 4.4 Robust scenario error-handling + container teardown (item 4)

- **Scenario resilience** (`planner/robust.py`). In `make_oracle_robust_rerank.rerank`, wrap each
  per-scenario `oracle.evaluate` in `try/except`; a failed scenario is logged and dropped (its KPIs
  omitted), never fatal. `robust_select` operates on the variable-length per-finalist scenario lists and
  requires **≥ ⌈N_requested/2⌉ successful scenarios** for a finalist to count as robust-feasible; a
  finalist with too few successes is treated as **not** robust-feasible (conservative). The `robust` block
  records `scenarios_ok` / `n_scenarios`.
- **Container teardown** (`planner/oracle_worker.py`). In `evaluate_one`'s `finally`, after `env.close()`,
  best-effort stop+remove the EnergyPlus Docker container via the dctwin backend handle (discovered off
  `env.unwrapped.eplus_backend`), each guarded so teardown never raises. Prevents container + BCVTB socket
  leaks on a hung/timed-out run.

## 5. Data-contract changes

- `recommendation.json`: `schema_version` → **1.3**; `forecast` block becomes
  `{"method", "weather", "bands"}` (real source, not hardcoded TMY); `robust` block gains `scenarios_ok`.
- SQLite `plans` index: new column `realized_energy_kwh`; `PlanSummary` gains the field.
- New endpoint `GET /api/plans/{id}/trajectory` → `{nominal, worst}` series.
- New artifacts: `runs/<id>/prevalidation/trajectory_worst.csv`.

## 6. Error handling

- Trajectory endpoint: a missing/empty CSV yields an empty series (200), never an error — the UI hides the
  card when both are empty.
- `validate_plan_request` failures are surfaced as 422 with the specific message; the plan is never created.
- A failed scenario degrades gracefully (dropped + counted); all-scenarios-failed → finalist not
  robust-feasible → the NOW-tier gate blocks approval (no silent pass).
- Container teardown is best-effort and fully exception-guarded.

## 7. Testing strategy

**Unit (no EnergyPlus):**
- `pipeline.validate_plan_request`: accept the defaults; reject grid<2, beam_width<1, max_evals<=0,
  days<1, negative weight — each with the right message.
- Trajectory: `store.get_trajectory` parses two fixture CSVs → two series; `GET /trajectory` returns
  `{nominal, worst}` (TestClient, fixture files); empty when absent.
- `MockEvaluator.replay_with_trajectory` returns paired `(kpi, samples)` (already exists; assert shape).
- `robust_select`: a dropped/failed scenario (short list) + the ⌈N/2⌉ rule → finalist marked not
  robust-feasible; `scenarios_ok` recorded.
- `build_recommendation`: schema 1.3 `forecast` carries real weather basename + bands; default still TMY
  when no weather file.
- `store`: `realized_energy_kwh` round-trips; `list_plans` exposes it.
- `objective`: `inlet_forecast_margin=0.0` is a no-op; `>0` rejects a candidate whose
  `inlet_temp_max + margin > inlet_cap` even with zero violation steps.

**Frontend (vitest):** trajectory `LineChart` renders nominal+worst+cap from a mocked `getTrajectory`;
History trend chart renders predicted+realized; `getTrajectory` client shape.

**Integration (Docker-gated, marker `integration`):** one real plan emits both trajectory CSVs;
`GET /trajectory` returns non-empty `nominal` and `worst`; the worst series shows higher inlet than nominal.

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **N1** | `validate_plan_request` + 422 wiring (+ unit tests) | startup fail-fast |
| **N2** | `ParallelEnvOracle.replay_with_trajectory` + `run_episode_with_samples` | real per-step capture |
| **N3** | `prevalidation` worst-case replay → `trajectory_worst.csv` | both trajectories emitted |
| **N4** | `store.get_trajectory` + `GET /api/plans/{id}/trajectory` (+ tests) | trajectory API |
| **N5** | `store` `realized_energy_kwh` column + `PlanSummary` | History trend data |
| **N6** | Review trajectory chart + History trend chart + `api.ts` (+ vitest) | the visibility UI |
| **N7** | Re-enable real-weather pkl + schema 1.3 `forecast_meta` + honest labels | forecast realism |
| **N8** | `ObjectiveWeights.inlet_forecast_margin` (off by default) | the margin hook |
| **N9** | robust scenario try/except + ⌈N/2⌉ rule + `scenarios_ok` | scenario resilience |
| **N10** | oracle_worker best-effort container teardown | leak prevention |
| **N11** | Docker integration: both trajectories emitted + served | acceptance |

N1–N6 deliver the operator-visible feature; N7–N10 are backend hardening; N11 is the realized proof.

## 9. Reference file index

- Trajectory: `planner/oracle.py`, `planner/oracle_worker.py`, `prevalidation.py`, `planner/trajectory.py`,
  `planner/kpi.py::step_trajectory`, `webapp/store.py`, `webapp/main.py`,
  `frontend/src/{api.ts, pages/Review.tsx, pages/History.tsx}`.
- Fail-fast: `planner/pipeline.py`, `planner/env_actions.py`, `webapp/main.py`.
- Forecast: `fit_forecaster.py`, `planner/forecaster.py`, `planner/recommendation.py`,
  `planner/objective.py`, `data/weather/Singapore_Changi_Nov2024-Jan2025.epw`.
- Robust/teardown: `planner/robust.py`, `planner/oracle_worker.py`.
- Predecessor: `docs/superpowers/specs/2026-06-07-close-fidelity-safety-gap-design.md`.
