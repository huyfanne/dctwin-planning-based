# Stage 6 — Physics Re-calibration · Rack Breakdown · Weather Uncertainty · Tariff Objective · Data-driven Robustness

- **Date:** 2026-06-11 · roadmap items 5–9.
- **Honesty rule:** every new capability must be exercisable today (sim telemetry / historical
  EPW) and field-connectable later; no invented constants silently changing recommendations.

## #5 + #9 — Physics re-calibration + data-driven robustness (one builder)

`planner/recalibrator.py` (currently a no-op seam) becomes real:
- `fit_plant_factors(history, min_weeks=4) -> Optional[dict]`: from the paired
  (predicted, realized) energy history, estimate a **fan-efficiency correction**: a persistent
  energy bias fraction `b = mean(realized/predicted) - 1` maps to
  `fan_total_efficiency_factor = clip(1/(1+b), 0.85, 1.15)` (more realized energy than
  predicted ⇒ the real fans are less efficient than modeled). Returns None below `min_weeks`
  or when |b| < 1% (no actionable drift). Conservative, explainable, monotone.
- `recalibrate(...)` (existing signature) now calls `fit_plant_factors` and returns
  `{"perturbations": [{"table":"Fan:VariableVolume","field":"fan_total_efficiency",
  "factor": f}], "basis": {...}}` or None.
- Persistence seam: `data/plant_calibration.json` written by the deploy loop
  (`webapp/jobs.py` after `recompute_calibration`) when a proposal exists.
- **#9 wiring:** `planner/plant.py` gains `load_plant_config(path="data/plant_calibration.json")`
  → a `PlantConfig` whose factors override/extend `DEFAULT_PLANT` (absent file → DEFAULT_PLANT
  exactly). `make_oracle_robust_rerank` uses it as the ensemble **center** (the believed plant
  state becomes data-driven). `n_scenarios` already plumbed via jobs params — expose it in
  `PlanParams` (webapp/schemas.py) with default 4, bounds 2–8, and pass through (jobs.py
  already reads `params.get("n_scenarios", 4)`).
- Owner files: planner/recalibrator.py, planner/plant.py, planner/robust.py (center only),
  webapp/jobs.py, webapp/schemas.py, tests (test_recalibrator, test_plant, test_robust,
  test_jobs additive).

## #6 — Per-rack / per-ACU breakdown (frontend builder)

Hotspot visibility from the live telemetry (22 `rack_inlet_c/ite-N` points already stream):
- **Live.tsx**: add a "Rack detail" table (rank by inlet desc: rack, inlet, margin-to-cap,
  status chip) under the heat-map — the operator's hotspot list. Reuse existing fetch state.
- **DigitalTwin3D.tsx**: color the controlled hall's rack rows by LIVE per-rack inlet
  (poll `getLive()` every 5 s; map ite-1..22 across the 6 rack rows in row-major order — 22
  units over the rows; document the mapping as schematic). Green<24.5 / amber<25.5 / red≥25.5.
  Add a small legend + "live telemetry" caption; keep the existing plan-based HUD.
- Owner files: frontend/src/pages/Live.tsx + test, DigitalTwin3D.tsx + test, api.ts (only if
  a type is missing).

## #7 — Weather forecast + uncertainty (planner builder)

`planner/weather_forecast.py` (new):
- `weather_stats(epw_path, week_start, days=7) -> {"mean_c", "sigma_c", "n"}`: dry-bulb mean
  + std of the **window ±7 days around the same month-days** in the EPW (the historical-analog
  spread = honest short-horizon uncertainty without an external API).
- `write_epw_variant(epw_path, out_path, delta_c)`: copy the EPW with dry-bulb shifted by
  `delta_c` (column 6; clamp dew-point ≤ dry-bulb). Returns out_path.
- `weather_scenarios(epw_path, week_start, out_dir, k=1.0) -> list[{"label","epw","delta_c"}]`:
  `[("nominal", original, 0), ("hot", +k·sigma), ("cool", −k·sigma)]`.
- The **seam for a real forecast API** is documented in the module docstring (replace
  weather_stats with the provider's mean/sigma; everything downstream is unchanged).
- Integration (done by the integrator, NOT this builder): the robust rerank adds ONE
  hot-weather scenario (nominal plant + hot EPW) so weather uncertainty tightens the gate the
  same way plant uncertainty does.
- Owner files: planner/weather_forecast.py, tests/test_weather_forecast.py only.

## #8 — Carbon/tariff-aware objective (planner builder)

- `planner/tariff.py` (new): `load_tariff(path="data/tariff.json") -> Optional[Tariff]`;
  `Tariff(kind, rates)` where rates is 24 hourly weights (price $/kWh or carbon kgCO2/kWh).
  Absent file → None → **behavior identical to today** (test-asserted).
- `planner/kpi.py`: `OracleSettings` gains `tariff_rates: Optional[tuple] = None` (24 floats)
  + `week_start_hour: int = 0`; `aggregate_kpi` additionally computes
  `WeeklyKPI.weighted_energy_cost` = Σ step_energy_kwh · rate[hour_of_step] (None when no
  tariff). Types: WeeklyKPI gains `weighted_energy_cost: Optional[float] = None` (additive,
  default None — picklable, backward-compatible).
- `planner/objective.py`: `score()` uses `weighted_energy_cost` **instead of** raw energy when
  present (same penalties); feasibility unchanged (safety never trades against price).
- `recommendation.py`: surface `weighted_energy_cost` + the tariff kind in `predicted_kpis`
  when present (schema unchanged — KPI dict is open).
- Owner files: planner/tariff.py, planner/kpi.py, planner/objective.py,
  planner/recommendation.py, planner/types.py (WeeklyKPI field), tests.

## Integration (the integrator does)

1. jobs.py already passes settings: thread `tariff` into OracleConfig settings via
   `load_tariff()` (one line) — only if absent-file default proven no-op.
2. robust rerank: append the hot-weather scenario from #7 when the EPW is known.
3. Full suites, frontend build, restart, driver smoke, Live + 3D screenshots, merge, graphify.

## Acceptance
- All defaults are provable no-ops (no tariff file, no plant_calibration file, no weather
  scenario unless wired): existing 376-test behavior unchanged except additive fields.
- Operator value visible: rack hotspot table + 3-D live coloring; n_scenarios in the API;
  tariff switches the optimization target only when the operator provides data/tariff.json.
