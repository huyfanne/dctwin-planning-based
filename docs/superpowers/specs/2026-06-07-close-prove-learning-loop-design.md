# Close & Prove the Learning Loop — Design Spec (LATER sub-project A)

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope tier:** the first **LATER** sub-project (the LATER tier was decomposed; FC joint-scenarios,
  ML forecaster, real BMS adapter, per-hall/time-block setpoints, and WebSocket progress are separate,
  later sub-projects).
- **Predecessor specs (merged):** `2026-06-07-close-fidelity-safety-gap-design.md` (NOW),
  `2026-06-07-next-tier-visibility-hardening-design.md` (NEXT).

---

## 1. Context & problem statement

The NOW tier gated the *deploy* against unsafe plans; the NEXT tier made the safety state visible and added
an **off-by-default** `inlet_forecast_margin` feasibility hook. Three loose ends remain in the "learning"
story:

1. **The search is not safe-by-construction.** A plan can be optimized right up to the 26 °C cap and only
   be caught later by the robust gate (→ `blocked_unsafe`) or the deploy backstop. The optimizer should
   avoid near-cap plans up front, using the uncertainty the calibration loop already measures.
2. **The forecaster sub-loop is ambiguously "open."** The original §9 claimed "realized System Data feeds
   the next week's forecaster," but the realized record is *aggregate weekly KPIs* (`advance_history` →
   `realized_history.csv`), while the forecaster needs *per-step IT-load* (`his_data_processed.csv`,
   15-min × 384 cols — incompatible). In sim-only mode the load *is* the forecast (the perturbed plant
   degrades cooling, not load), so there is **no new load signal**. The real realized-feedback path is the
   **calibration** loop, which is already closed.
3. **The loop is never proven to converge** over multiple weeks.

**Goal:** make plans **safe-by-construction** at search time (A1), **honestly settle** the forecaster
sub-loop (A2), and **prove** the calibration loop converges (A3).

## 2. Goals / non-goals

**Goals**
- A1: auto-derive a `k·σ` inlet pre-tighten from the calibration σ each plan, applied to BOTH the inner
  beam search and the robust scenario feasibility checks; on by default (`k=1.0`); auto-relaxes as σ shrinks.
- A2: make `refit_from_history` an explicit documented no-op seam; correct the §9 over-claim (calibration
  is the sim feedback path; forecaster refit needs real per-step telemetry).
- A3: a fast unit-level multi-week loop driver that proves convergence (σ non-increasing, bias stabilizes,
  plans become and stay realized-feasible).

**Non-goals (parked / other sub-projects)**
- FC joint plant×load robustness; ML forecaster (both data-gated — flat telemetry, persistence wins).
- Real BMS adapter (hardware-gated).
- Per-hall / time-block setpoints (sub-project B); WebSocket progress (sub-project C).
- No new heavy multi-week **Docker** test — the single-week real-EnergyPlus path is already covered by the
  existing integration suite; the BCVTB co-sim is too slow/flaky for an N-week loop (a 95-min hang was
  observed). The unit-level driver covers the multi-week *dynamics*.

## 3. Decisions locked during brainstorming

| Question | Decision |
|---|---|
| A1 activation | **On by default, `k = 1.0`** (`K_SIGMA` constant). |
| A1 cold-start | When `n_weeks == 0`, use `SIGMA_PRIOR["inlet_temp_max_c"]` (≈1 °C) so even the first plan is conservative. |
| A1 scope | Same margin-adjusted `ObjectiveWeights` flow into the inner search AND the robust rerank. |
| A2 | Honest **no-op seam** + §9 erratum (calibration is the sim feedback; forecaster refit needs real telemetry). |
| A3 | **Unit-level** convergence proof only (no new Docker test). |

## 4. Component design

### 4.1 A1 — k·σ search-time inlet pre-tighten

A pure helper derives the margin from calibration (idempotent — it **sets**, never accumulates):

```python
# planner/pipeline.py
K_SIGMA = 1.0

def apply_forecast_margin(weights: ObjectiveWeights, calibration, k_sigma: float = K_SIGMA) -> ObjectiveWeights:
    """Set inlet_forecast_margin = k * sigma_inlet (sigma from calibration once weeks exist,
    else the cold-start SIGMA_PRIOR). Idempotent. calibration is None -> weights unchanged."""
    if calibration is None:
        return weights
    sigma = (calibration.sigma_for("inlet_temp_max_c") if calibration.n_weeks > 0
             else SIGMA_PRIOR["inlet_temp_max_c"])
    return dataclasses.replace(weights, inlet_forecast_margin=k_sigma * sigma)
```

- `run_weekly_plan` applies it once near the top: `weights = apply_forecast_margin(weights or ObjectiveWeights(), calibration)`. The pre-tightened `weights` then flow into the `BeamPlanner` (inner search rejects candidates with `inlet_temp_max + margin > inlet_cap`, via the NEXT-tier `is_feasible` gate).
- `webapp/jobs.py::run_plan_job` applies the **same** helper to the weights it passes to
  `make_oracle_robust_rerank(weights=...)`, so the robust scenario feasibility checks pre-tighten
  identically. Because the helper is idempotent and both call sites derive from the same `calibration`,
  the margins are consistent with no double-application.
- The recommendation records the applied values: `build_recommendation` gains `inlet_forecast_margin` +
  `k_sigma` as **top-level** recommendation fields (present regardless of whether a `robust` block exists);
  `schema_version` → **1.4**.

**Behavior:** at true cold-start the margin is `1.0 × SIGMA_PRIOR ≈ 1 °C` (cap treated as ≈25 °C); after
deploys it tracks `1.0 × σ_inlet`, shrinking toward the sample std as the twin proves accurate. The robust
gate + deploy backstop remain the net for whatever the margin doesn't pre-empt.

### 4.2 A2 — Forecaster sub-loop: honest no-op seam

- `planner/history.py::refit_from_history` becomes an explicit documented **no-op** (returns `None`,
  mirroring `recalibrator.recalibrate`): the misleading `runpy.run_path("fit_forecaster.py")` body is
  removed (it would re-fit on unchanged per-step data and has zero callers). The docstring states: in
  sim-only mode the realized load equals the injected forecast, so there is no forecaster feedback;
  the **calibration** loop is the realized-feedback path; this seam activates only with real per-step
  telemetry.
- `advance_history` (the `realized_history.csv` writer) is unchanged but its docstring notes it is a
  realized-KPI record (read by humans / future telemetry work), not a forecaster input.
- **Spec erratum** appended to `docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md`
  §9 (or a short note in this spec referencing it): "realized System Data feeds the next week's
  forecaster" holds only with real per-step telemetry; in sim-only v1 the realized-feedback path is
  calibration.

### 4.3 A3 — Multi-week convergence proof (unit-level)

A new `tests/test_loop_convergence.py` drives N weeks of the loop with **no EnergyPlus**:
- A deterministic **mock plant** = the `MockEvaluator` twin's KPI plus a fixed inlet bias `Δ` (e.g. the
  twin predicts inlet `x`, the "plant" realizes `x + Δ`, `Δ ≈ 2 °C`) and a fixed energy bias.
- Each week: build the calibration → `apply_forecast_margin` → `run_weekly_plan` (MockEvaluator, the mock
  calibration) → take the winner → "deploy" on the mock plant → `advance_calibration` (raw predicted vs
  realized) → `recompute_calibration` → next week.
- Assertions over N = 4 weeks:
  - calibration `sigma["inlet_temp_max_c"]` is **non-increasing** week-over-week (converges),
  - `|bias_week - bias_{week-1}|` **shrinks** (bias stabilizes),
  - by week ≥ 2 the re-planned winner is **realized-feasible** on the mock plant (0 inlet violations),
  - the plan does not regress to `blocked_unsafe`/`infeasible_fallback` after convergence.

This proves the loop dynamics deterministically and runs in milliseconds.

## 5. Data-contract changes

- `recommendation.json`: `schema_version` → **1.4**; new **top-level** fields `inlet_forecast_margin`
  (°C applied this plan) and `k_sigma` (the constant), recorded so an operator can see how conservative
  the search was.
- No API, store, or frontend changes.

## 6. Error handling

- `apply_forecast_margin` with `calibration=None` is a no-op (margin 0) — unit tests and any caller
  without calibration keep current behavior.
- If σ is absurdly large (e.g. a poisoned calibration), the pre-tighten could make the whole grid
  infeasible → the existing `infeasible_fallback` path handles it (no new failure mode); the NOW-tier
  σ-floor/clip already bounds σ.

## 7. Testing strategy

**Unit (no EnergyPlus):**
- `apply_forecast_margin`: `calibration=None` → unchanged; `n_weeks==0` → `k·SIGMA_PRIOR`; `n_weeks>0` →
  `k·σ`; idempotent (applying twice == once).
- `run_weekly_plan`: with a calibration whose σ_inlet is large, a near-cap MockEvaluator surface yields
  fewer feasible candidates than with σ=0 (the pre-tighten actually bites); recommendation carries
  `inlet_forecast_margin`/`k_sigma` and `schema_version == "1.4"`.
- `objective.is_feasible`: already covered by the NEXT tier (margin gate); add a case asserting the margin
  derived from σ rejects an `inlet_temp_max` within `k·σ` of the cap.
- `history.refit_from_history` returns `None` (documented no-op); no file side effects.
- `test_loop_convergence`: the N-week driver assertions in §4.3.

**No frontend, no new Docker tests.**

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **L1** | `apply_forecast_margin` helper + `K_SIGMA` (+ unit tests) | margin derivation |
| **L2** | wire it into `run_weekly_plan` (inner search) | safe-by-construction search |
| **L3** | wire the same margin into `run_plan_job`'s robust rerank weights | consistent robust gate |
| **L4** | `build_recommendation` `inlet_forecast_margin`/`k_sigma` + schema 1.4 | auditability |
| **L5** | `refit_from_history` → documented no-op + §9 erratum | honest forecaster seam |
| **L6** | `test_loop_convergence` multi-week driver | convergence proof |

L1–L4 are the safe-by-construction feature; L5 is the honesty fix; L6 is the proof.

## 9. Reference file index

- A1: `planner/pipeline.py` (`run_weekly_plan`, new helper), `webapp/jobs.py::run_plan_job`,
  `planner/objective.py` (`is_feasible` margin gate, already present), `planner/calibrator.py`
  (`SIGMA_PRIOR`, `Calibration.sigma_for`), `planner/recommendation.py` (schema 1.4).
- A2: `planner/history.py::refit_from_history`, `planner/recalibrator.py` (the seam to mirror),
  `docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` §9.
- A3: `tests/test_loop_convergence.py` (new), `planner/mock_evaluator.py`, `planner/calibrator.py`,
  `planner/history.py::advance_calibration`.
