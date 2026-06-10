# Robust-Gate Uncertainty Allocation — Design Note

- **Date:** 2026-06-10
- **Status:** Implemented (follow-up to the 2026-06-10 blocked_unsafe deadlock fix)
- **Scope:** `planner/calibrator.py` (sigma_post), `planner/robust.py` (scenario_spread, make_oracle_robust_rerank)

## Problem

After the deadlock fix, every cold-start plan resolved to the as-operated baseline (0%
saving): no cheaper setpoint could be *proven* robust. Evidence said the conservatism was
miscalibrated, not the physics: the one deployed week measured the twin's peak-inlet
prediction error at **+0.005 °C**, yet the gate still hedged with (a) the full 1.0 °C prior
margin AND (b) a ±10% perturbed-plant ensemble AND (c) required (a) *inside* (b).

## Physical analysis — where the conservatism was unprincipled

**1. Double-counted uncertainty.** The k·σ margin exists to hedge *twin-vs-plant model
error* where no degradation is physically modeled (the nominal check). A robust scenario
*physically realizes* a degraded plant — fan efficiency and coil water flow are actually
reduced in the IDF. Requiring inlet ≤ cap − 1.0 °C *inside* a plant already degraded
~17–24% hedges the same uncertainty twice, multiplicatively. No physical reading supports
it: the scenario's purpose is to BE the hedge.

**2. Ensemble width pinned to an unmeasured prior.** `scenario_spread` scaled with the
fading-floor σ, which by construction stays at the full 1.0 °C prior at n=1 (sample std of
one residual is 0). So the ensemble stayed at maximum width exactly when the first
measurement said the twin was accurate. The floor is the right statistic for the *margin*
(never under-state error at small n — asymmetric cost), but the wrong one for *sizing the
ensemble*, which is an additional, independent hedge.

## The allocation (implemented)

| Layer | Hedges | Width | Changed? |
|---|---|---|---|
| Nominal beam check | twin model error (no degradation modeled) | cap − k·σ, σ = fading floor (1.0 °C cold start) | **unchanged** |
| Robust scenarios | plant-state/degradation uncertainty | each scenario KPI **bias-corrected** (measured systematic error), then tested vs the **hard 26 °C cap** | margin no longer stacked inside scenarios |
| Ensemble width | how wrong the believed plant state may be | `base · σ_post/σ_ref`, clamped to [0.02, base] | σ_post replaces floor-σ |
| Deploy backstop | everything incl. discrete failures | realized week: 0-tolerance inlet breach → deploy_blocked | unchanged |

**σ_post (empirical-Bayes):** `sqrt((n·s² + σ_prior²)/(n+1))` — the prior counts as one
pseudo-week of evidence. n=0 → prior (cold start exactly as conservative as before);
n=1, s≈0 → prior/√2 (one accurate week buys a √2 tightening, not collapse); n→∞ → s
(the measurement). Stored alongside the fading-floor σ in `calibration.json`
(`sigma_post`); legacy files without it fall back to the floor σ (never less conservative
than the old behavior).

**MIN_SPREAD = 0.02:** the ensemble never collapses below ±2% parameter drift — a
generous bound on week-scale fouling/filter-loading/fan-wear under normal operation.
Past accuracy is not immunity to future drift. Discrete failures (chiller trip) are not
coverable by any continuous ensemble; they belong to the deploy backstop + monitoring.

## What this is NOT

Not a weakening of the safety invariant. The hard inlet ≤ 26 °C cap binds in every layer;
the nominal k·σ margin is untouched; the worst modeled plant must still hold the hard cap
after bias correction; pre-validation and the deploy backstop are untouched. The change
removes a *double*-hedge and replaces an unmeasured constant with a measurement-driven,
floored estimate.

## Measured effect (real EnergyPlus, week 2024-11-08, n_weeks=1)

- Ensemble width 0.1 → **0.0707** (σ_post = 0.7071).
- Scenario feasibility now = bias-corrected hard cap (was cap − 1.0 °C inside scenarios).
- See the verification run in the merge commit for the resulting recommendation/saving.
