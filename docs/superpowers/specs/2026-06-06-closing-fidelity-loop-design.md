# Closing the Fidelity Loop — Design Spec (P1 + P2)

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan.
**Builds on:** `2026-06-04-digital-twin-dual-loop-control-design.md` (v1 framework) and the
first-draft review (`dctwin/dctwin/BHUMANS/review_after_1st_draft.md`).

## 1. Context & objective

The v1 framework's **inner planning loop** (forecast → beam search → EnergyPlus oracle →
recommendation) is complete and verified. The **outer loop** stops at the expert gate: `deploy()`
exists but is orphaned (no endpoint), realized outcomes are never fed back, and the twin is never
calibrated (twin == plant). The objective is a **Digital Twin deployment for weekly operation with
high-fidelity recommendations**. This spec delivers the two decisive increments from the review:

- **P1 — close the deploy → realize → refit loop.**
- **P2 — twin calibration + forecast realism + uncertainty**, used to produce **robust** (under
  model mismatch) recommendations.

## 2. Goals / non-goals

**Goals**
- Physically close the outer loop in simulation: deploy an approved plan to a **plant**, capture
  realized KPIs, persist them, and refit the forecaster for the next week.
- Introduce a **perturbed-plant** (twin ≠ plant) so there is a real mismatch to calibrate against
  and to quantify uncertainty.
- **Calibrate** the twin to the plant each week (staged: output-residual now, physics-recal seam
  later) and **quantify uncertainty**.
- Make recommendations **robust**: 0 inlet violations under the calibrated mismatch, with confidence
  bands surfaced to the expert.

**Non-goals**
- No real BMS / real telemetry (the `deploy()`/plant seam is the future hook).
- No ML forecaster.
- No physics recalibration *behavior* in v1 (interface seam only).
- No time-varying / per-hall setpoints (separate future spec — the "control sequences" item).

## 3. Locked decisions (anchors)

| Dimension | Choice |
|---|---|
| Data/deployment reality | **Simulation-only + perturbed-plant** (sim E+ is the plant; `deploy()` stays the future-BMS seam) |
| Perturbed-plant gap | **Parameter/physics perturbation** (coil fouling, fan efficiency, infiltration) |
| Calibration | **Staged** — learned output-residual correction now (+ uncertainty); E+ parameter recalibration later (seam) |
| Uncertainty usage | **Scenario/ensemble robust** selection over finalists |
| Robust rule | **Worst-case feasibility** (inlet ≤ 26 °C in every scenario) + **CVaR_α objective** (robust-average energy) |
| Build shape | **Approach 1** — layered closed fidelity loop, phased P1 → P2a → P2b, behind existing `Evaluator`/`deploy()` seams |

## 4. Architecture & the weekly loop

Two models, one engine: the same dctwin/EnergyPlus oracle runs two parameter sets — the **twin**
(nominal `models/building.json` → IDF, what the planner optimizes against) and the **plant** (same
model with perturbed physical params, the deploy-only ground truth).

```
            ┌─────────────────────────────────────────────────────────────┐
            │                                                               │
            ▼                                                               │
 (1) Forecast ──► (2) Plan (inner, point-estimate)  ──► (3) Robust re-rank  │
   forecaster        BeamPlanner vs TWIN, calibrated      top-K finalists × │
   (refit on         objective → top-K beam              ensemble scenarios │
    realized)                                            → robust winner +  │
            ▲                                              confidence bands │
            │                                                     │         │
            │                                                     ▼         │
 (6) Calibrate + refit ◄── (5) Deploy: run PLANT  ◄── (4) Pre-validate +    │
   residual correction       (perturbed params)        expert approve/edit  │
   + uncertainty;            → realized KPIs                                 │
   append realized to                                                       │
   his_data ──────────────────────────────────────────────────────────────┘
```

1. **Forecast** — `StatisticalForecaster`, refit on accumulated realized data, produces the week's
   workload (+ error spread).
2. **Plan (inner, fast)** — `BeamPlanner` + `ParallelEnvOracle` search the 3-setpoint cube against
   the twin, scored by the **calibrated** objective — as today — producing the top-K beam.
3. **Robust re-rank (P2b)** — re-evaluate only the top-K finalists across an ensemble of
   perturbed-twin scenarios; pick the robust winner; attach confidence bands → `recommendation.json`.
4. **Pre-validate + expert gate** — unchanged.
5. **Deploy (P1)** — on approval, `POST /deploy` runs the perturbed **plant** for the week →
   realized KPIs.
6. **Calibrate + refit (P2a)** — append realized to history; `Calibrator` updates the residual
   correction + uncertainty; forecaster refits → feeds next week's steps 1–3.

Over weeks the twin is corrected toward the plant, the uncertainty band shrinks, and recommendations
stay 0-violation under the calibrated mismatch.

## 5. Components & interfaces

All additive to the `planner/` package and `webapp/`. Each unit is independently testable with a
mock oracle; the planner depends only on `Evaluator` + `Calibration` (not on the plant or web layer).

**5.1 `planner/plant.py` — PerturbedPlant**
- Does: plant's EnergyPlus run = nominal model + physical-parameter perturbations.
- Interface: `PlantConfig` = list of `{object, field, factor}` (e.g. `Coil:Cooling:Water UA ×0.85`,
  `Fan efficiency ×0.93`, `ZoneInfiltration ×1.2`); `apply_perturbation(idf, PlantConfig) ->
  perturbed_idf`. Reuses the oracle via a `param_overrides` field on `EvalTask` so `evaluate_one`
  builds the env from the perturbed IDF.
- Depends on: IDF + dctwin `make_env`. Used by: deploy (P1) and robust scenarios (P2b).

**5.2 Deploy loop (P1)** — `webapp/main.py` route + `webapp/jobs.py` worker + `planner/deploy.py`
- Does: runs the plant for the approved week, captures realized KPIs, persists, refits the forecaster.
- Interface: `POST /api/plans/{id}/deploy` (expert) → `run_deploy_job(id)` → `deploy(rec,
  plant_oracle, forecast)` (exists, gated on `approved`) → `realized_kpis`. Then
  `store.save_realized`, status → `deployed`, append realized workload+KPIs to the forecaster
  history, schedule refit.
- Depends on: PerturbedPlant, `PlanStore`, forecaster.

**5.3 `planner/calibrator.py` — Calibrator (P2a)**
- Does: from realized-vs-predicted history, learns a correction + uncertainty.
- Interface: `Calibrator.update(history) -> Calibration`; `Calibration.apply(kpi) -> corrected_kpi`,
  `Calibration.sigma(name) -> float` / `.sample(n)`. Persisted as `calibration.json` (versioned).
- Depends on: realized history. Used by: the objective (corrected predictions) + robust stage
  (uncertainty → scenario spread).

**5.4 `planner/robust.py` — Robust planner stage (P2b)**
- Does: re-evaluates top-K finalists across an ensemble, picks the robust winner, attaches bands.
- Interface: `make_scenarios(Calibration, n) -> ScenarioSet`; `robust_rerank(finalists, scenarios,
  oracle, rule) -> (winner, per_finalist, bands)`. Wired into `pipeline.run_weekly_plan` after the
  beam search. Cost: K × n full-week runs.
- Depends on: oracle, Calibration, beam finalists.

**5.5 `planner/recalibrator.py` — Recalibrator seam (P2c, not built)**
- Does (future): tune the twin's physical params toward the plant once enough weeks accumulate.
- Interface (stub): `Recalibrator.recalibrate(history) -> ParamUpdate` — documented no-op in v1.

## 6. Algorithms & key decisions

**6.1 Calibration.** Per-KPI residual model over the deploy history: additive
`bias = mean(realized − predicted)`, `σ = std(realized − predicted)` per KPI (inlet, energy, PUE);
upgrade to affine `realized ≈ a·predicted + b` once ≥ ~4 weeks. Inlet is safety-critical:
`corrected_inlet = predicted_inlet + bias_inlet`. Cold-start: identity bias, σ = conservative prior
from the perturbation range; σ shrinks toward the true spread over weeks (optional exponential
recency weighting for drift; bounded per-week step; clip residual outliers).

**6.2 Corrected objective.** The inner beam search scores candidates on `Calibration.apply(kpi)`, so
the fast point-estimate pass is already bias-corrected.

**6.3 Ensemble scenarios.** N draws of plausible plant parameter perturbations from a prior range
**rescaled by the calibrated σ** so the ensemble brackets the observed mismatch (wide at cold-start,
tightening over weeks). Default **N = 4**, top **K = 5** finalists (~20 extra full-week runs, ~+8%,
parallelized).

**6.4 Robust rule (the split).**
- **Safety → worst-case.** A finalist is robust-feasible only if inlet ≤ 26 °C in *every* scenario.
- **Energy → CVaR_α.** Among robust-feasible finalists, rank by CVaR_α of energy (mean of the worst
  α-tail); pick the min-CVaR winner. Default **α = 0.8**.
- Rationale: worst-case on the *constraint* (safety must always hold), CVaR on the *cost* (tunable
  risk aversion) — avoids the over-conservatism of worst-case-everything.

**6.5 Efficiency.** During the beam search, pre-tighten the inlet gate to
`corrected_inlet + k·σ ≤ 26` (default **k = 1.0**) so finalists are already likely robust-feasible;
the ensemble confirms.

**6.6 Confidence bands.** For the winner, report per-KPI quantiles across scenarios (inlet
p50/p90/max, energy p50/p90) → `recommendation.json` + UI.

**Tunables (all defaulted):** `N=4`, `K=5`, `α=0.8`, `k=1.0`, ensemble-spread scale.

## 7. Data contracts, API, state machine, error handling

**7.1 Artifacts**
- `recommendation.json` → **schema 1.1**: add a `robust` block (`winner`, `robust_feasible`,
  `cvar_energy_kwh`, `confidence_bands` p50/p90/max, `calibration_version`, `scenarios`).
- `runs/<id>/realized.json` (new): plant realized KPIs + per-step series.
- `calibration.json` (new, per-model, versioned): per-KPI bias/scale + σ + `n_weeks`.
- `configs/plant_perturbation.json` (new): the `PlantConfig` (versioned, auditable).
- Forecaster history append: realized workload+outcomes for refit.

**7.2 API**
- `POST /api/plans/{id}/deploy` (expert) → `deployed` / `deploy_failed`.
- `GET /api/plans/{id}` extended with `realized` + `robust`/bands when present.
- `GET /api/calibration` (operator) → current bias/σ/`n_weeks`.

**7.3 Status state machine** (`status` becomes an Enum; transitions validated):
```
pending_approval ──approve──► approved ──deploy──► deployed
       │                          ▲ deploy_failed (retry)
       └──reject──► rejected      │
infeasible_fallback ──(expert: reject | approve-with-caution)──►
```
`deploy` only from `approved`; `approve` only from `pending_approval` / `infeasible_fallback`.

**7.4 Error handling**
- Plant run fails: status `deploy_failed`, record error, do NOT advance calibration; retry allowed.
- Scenario run fails: drop it; require ≥ ⌈N/2⌉ successes else demote that finalist as "uncertain".
- No finalist robust-feasible: widen K / re-search with margin; else safest worst-case inlet +
  `infeasible_fallback` **with diagnostics** (which scenarios/constraint bound).
- Thin/garbage calibration data: cold-start prior; clip outliers; ignore failed deploys;
  recency-weighted, bounded step.
- Edited setpoints: `PATCH /setpoints` triggers a quick twin re-eval so predicted ≈ deployed.
- Provenance: log forecast + calibration version + scenario params + per-finalist robust scores +
  per-candidate failures.

## 8. Testing

**Unit (no Docker):** `calibrator` (fit/cold-start/recency/clip), `robust` (scenario spread +
worst-case feasibility + CVaR ranking + bands via MockEvaluator), `plant.apply_perturbation` (right
IDF fields/factors), status machine, deploy gate (refuses non-approved; calibration advances only on
success), schema round-trips (rec 1.1 / calibration.json / realized.json), route auth, and a
**loop-convergence** test (MockEvaluator emulating a parametric gap → calibrated residual shrinks /
corrected predictions improve over simulated weeks).

**Integration (Docker + E+, marked, skip if unavailable):** a 1-day perturbed-plant deploy (realized
≠ predicted; calibration updates) and a tiny end-to-end (forecast → small-grid plan → robust N=2 →
deploy → calibrate → next plan's σ/bias changed) — also closes the review's CI integration-test gap.

## 9. Phasing / milestones (each ships green; P1 closes the loop first)

- **P1 — loop closure:** M1 `PlantConfig`+`apply_perturbation`; M2 `/deploy` + `run_deploy_job` +
  `realized.json` + status machine; M3 realized→forecaster refit + GET shows realized.
- **P2a — calibration:** M4 `Calibrator` + `calibration.json` + corrected objective; M5
  `/api/calibration` + UI surfacing.
- **P2b — robust:** M6 scenarios + `robust_rerank` (worst-case feasibility + CVaR) wired into
  `pipeline` + rec 1.1/bands; M7 UI confidence bands; M8 integration tests.
- **P2c — seam:** `Recalibrator` stub + docs (no behavior).

## 10. Out of scope (YAGNI / separate efforts)

Real BMS/telemetry; ML forecaster; physics-recal *behavior* (seam only); time-varying / per-hall
setpoints (the "control sequences" item — its own future spec).

## 11. Open questions / future work

- Physics recalibration behavior (P2c) — when to trigger (drift detection), what params to tune.
- Whether to widen the action space (time-blocks / per-hall) once the fidelity loop is validated —
  at which point the search may move from beam to Bayesian optimization / CMA-ES.
- Real weather forecast ingestion (currently static TMY window).
