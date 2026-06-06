# Forecast Realism — Design Spec

**Date:** 2026-06-06
**Status:** Approved (design); pending implementation plan
**Builds on:** the closed fidelity loop (P1 deploy→realize→refit, P2a calibration, P2b scenario-robust selection). See `docs/superpowers/specs/2026-06-06-closing-fidelity-loop-design.md`.

## Problem

The Digital Twin's weekly recommendations are bounded by a naive forecast of the coming week's operating conditions:

1. **IT load** is forecast by *persistence* — `planner/forecaster.py` `persistence_window` simply takes the last *n* steps of historical loading and tiles them forward. The `method="seasonal-naive"` string is a misnomer: it runs the *same* persistence code. This smears the real diurnal cycle (peak ~21–23h SGT, trough ~04–06h) and weekly structure, and carries **no uncertainty**.
2. **Weather** is a *static* 1989-90 synthetic TMY (`data/weather/SGP_Singapore.486980_IWEC.epw`), hardcoded in `configs/dt/dt.prototxt` with a fixed simulation year (2013). The sim's outdoor conditions are therefore **decoupled** from the actual weather of the planned week — a real fidelity gap for cooling in tropical Singapore, where ambient wet-bulb drives chiller/tower load and economizer potential.

Plant fidelity (calibration) and plant uncertainty (robust selection) are already handled; the forecast of *next week's drivers* (load + weather) is the remaining fidelity gap.

## Available data (verified)

- **Real IT-load telemetry:** `data/his_data_processed.csv` — 6938 rows × 384 cols, **15-min resolution, 2024-11-05 08:00 → 2025-01-16 14:15 SGT** (72.3 days). Per-room IT loads, PUE/ACLF, rack hot/cold sensor temps + RH, chiller/cooling-tower water temps, 375+ device power columns. Loads are **low-utilization and flat** (~0.06–0.1% of nameplate); the exploitable signal is the diurnal/weekly *shape*, not large level swings. **No outdoor dry-bulb/RH column** (telemetry is internal + water-loop only).
- **Real weather (user-provided):** `data/weather/Singapore_Changi_Nov2024-Jan2025.epw` — **NASA POWER reanalysis, Singapore Changi (lat 1.367, lon 103.983, tz +8, elev 16 m), hourly, 2024-11-01 → 2025-01-31 (2208 rows)**. `DATA PERIODS` = one period, Friday 11/1 → 1/31. **Fully covers the telemetry window**, so any planning week in ~Nov 5 2024 – Jan 16 2025 has both real load history and real weather. Crosses the 2024→2025 year boundary.
- **Mappings:** `configs/dt/room2ite_map.json` (rooms→ITE capacity), `configs/dt/device_his_map.json` (E+ nodes→CSV columns).

## Goals

1. Replace persistence with a **real seasonal IT-load forecaster** (day-of-week × time-of-day climatology) that captures the diurnal/weekly shape and **emits p10/p50/p90 uncertainty bands**, with a **backtest** that proves it beats persistence on held-out real data.
2. Make EnergyPlus weather **per-forecast** (a real EPW for the planned week), replacing the static TMY, validated against the **real provided EPW**.
3. **Surface** forecast uncertainty (recommendation + UI) and **feed it into P2b** as joint (plant, load) robust scenarios so the robust winner is feasible under both plant *and* forecast uncertainty.

## Non-goals

- Per-ITE forecasting (room-level broadcast is retained; telemetry is room-granular for loads).
- Live BMS streaming / automated weekly refit pipeline (data is batch CSV; refit stays the existing `fit_forecaster.py` step).
- ML / ARIMA / Holt-Winters models (flat 72-day data does not justify them; YAGNI).
- Synthetic stress-load injection (separate concern).
- Sourcing weather via external APIs (the real EPW is provided).

## Architecture & phasing

Three cohesive, independently-shippable phases. Each becomes its own implementation plan (spec-section → plan → execute), as P1/P2a/P2b were.

```
FA  SeasonalForecaster (dow×tod climatology) + p10/p50/p90 bands + backtest harness
FB  Real-weather seam (per-forecast EPW; year/calendar alignment; cross-year)
FC  Uncertainty surfacing (recommendation schema 1.2 + UI) + P2b joint (plant,load) scenarios
```

Dependency: FC depends on FA (needs bands) and on the existing P2b robust stage; FB is independent of FA. Recommended build order FA → FB → FC.

---

## Component FA — `SeasonalForecaster` + uncertainty + backtest

### Forecaster

- New `method="seasonal"` — a *real* seasonal climatology, distinct from the misnamed `"seasonal-naive"` (which remains an alias of persistence for back-compat, with a deprecation note).
- **Climatology fit:** for each room, bin the real historical loading series (`loading_from_it_loads` output, fraction 0–1) by `(weekday 0–6, time-of-day bin)`. At 15-min resolution that is 7 × 96 = **672 buckets**; ~10 samples/bucket over 72 days. The point forecast for step *t* = the **mean** of the bucket matching `(weekday(t), tod(t))` for the requested `week_start`.
- **Bands:** per bucket, the empirical **p10 / p50 / p90** of the historical loadings in that bucket. The p50 series is the point forecast used for the search.
- **Thin-bucket fallback:** buckets with fewer than `MIN_BUCKET_SAMPLES` (e.g. 4) observations fall back to the **hour-of-day** pooled climatology (24 buckets), then to the global mean. The chosen bin width is a documented tunable (default 15-min to match the sim step; hour-of-day as the robust fallback).
- **Room broadcast** is retained: all ITEs in a room share the room's climatology (matches the telemetry granularity).

### `Forecast` object changes

```
Forecast:
  week_start: date
  workload_schedules: dict[str, list[float]]      # p50 point series per ITE (unchanged seam)
  method: str
  bands: Optional[dict[str, dict[str, list[float]]]]   # ITE -> {"p10","p50","p90"} per-step  [NEW]
  weather_file: Optional[str]                          # absolute EPW path (FB)               [NEW]
```

`materialize()` keeps writing the p50 `workload_schedules` to `data/schedule/workloads/<ite>.json` (the existing EnergyPlus seam is untouched). Bands are carried for FC; a band level can be materialized on demand (FC) by writing the chosen p-level series through the same path.

### Backtest harness

- `backtest_forecaster.py` (script + importable functions): hold out the last *N* days of `his_data_processed.csv`, fit seasonal on the remainder, forecast the held-out window, and report **per-room**:
  - **MAPE / RMSE** of seasonal vs persistence (seasonal must win on the diurnal-shaped rooms);
  - **band calibration / PICP** — fraction of held-out actuals inside [p10, p90] (target ≈ 0.80) and inside [p50±] — i.e. are the bands honest, not just narrow.
- Output: a printed/markdown report (e.g. `docs/forecast-backtest.md` or stdout) — substantiates the "realism" claim. Not a CI gate; covered by unit tests on synthetic data with a known seasonal pattern.

### Production wiring

- `fit_forecaster.py` records `method` in `models/forecaster.pkl`; setting it to `"seasonal"` makes `run_plan_job`/`run_deploy_job` construct the seasonal forecaster (no call-site change — they already pass `method=fc_cfg["method"]`).

---

## Component FB — Real-weather seam

### Seam

- `Forecast.weather_file: Optional[str]` carries an absolute EPW path. The forecaster attaches the configured weather file (from `forecaster.pkl`, new key `weather_file`) when present.
- `write_week_config(base_prototxt, week_start, out_path, days, timesteps_per_hour=None, weather_file=None)` — when `weather_file` is given, set the prototxt's `weather_file` field (today it is left at the hardcoded IWEC path). The oracle (`oracle.py`) passes `forecast.weather_file` through when it writes the week config.

### Year / calendar alignment (the hard part)

- Today `week_config.py` (`compute_week_period`) sets only `begin_month/day`, `end_month/day` and the codebase hardcodes year **2013** (`week_config.py`, `core.py`), **rejecting cross-year forecasts**. A real EPW with real dates needs the RunPeriod calendar to match:
  - Derive the simulation **year from `week_start.year`**; set EnergyPlus RunPeriod **Begin Year and End Year** explicitly (E+ 9.5 `RunPeriod` supports both) so a week may span the **2024→2025 boundary** (e.g. `week_start=2024-12-30`).
  - **Day-of-week alignment:** set RunPeriod's start day-of-week from the real calendar date (or `UseWeatherFile`) so weekday-dependent schedules + the EPW align. The provided EPW's `DATA PERIODS` (Friday 11/1/2024) is correct.
  - **Coverage validation:** the requested week must fall within the EPW's data period (Nov 1 2024 – Jan 31 2025 for the provided file); outside → clear error (or fall back to the static TMY with a logged warning). This replaces the blanket cross-year rejection.
- Lift/replace the hardcoded-2013 constant accordingly; keep the static-TMY path working when no `weather_file` is supplied (back-compat).

### Validation

- Validated directly against the **real provided EPW** (`Singapore_Changi_Nov2024-Jan2025.epw`): a planning week inside the coverage runs EnergyPlus on the real weather for the real dates. The static IWEC EPW remains the default when no weather file is configured.

---

## Component FC — Uncertainty surfacing + P2b joint scenarios

### Surfacing

- **Recommendation schema 1.2:** extend the existing `forecast` block (`{method, weather}`) with `method` (e.g. `"seasonal"`), `weather_file` / weather source label, and a **load-band summary** (aggregate or per-room p10/p50/p90 of the forecast). Schema bumps 1.1 → 1.2 only when the band/weather detail is present (back-compat preserved).
- **UI:** a "Forecast" card in `Review.tsx` (method, weather source, load band p10/p50/p90), reusing the existing card/table styling.

### P2b joint (plant, load) scenarios

- A scenario becomes a **(PlantConfig, load-trajectory) pair**. `make_scenarios` (extended, or a new `make_joint_scenarios`) builds **J joint draws** pairing plant perturbations with load bands drawn from the forecast — explicitly including the dangerous **correlated** case (degraded plant **and** p90 load). Example J=6: `(nominal,p50)`, `(fouled,p90)`, `(degraded,p90)`, `(nominal,p10)`, `(fouled,p50)`, `(degraded,p50)`. The plant draws reuse FB-independent `make_scenarios`/`scenario_spread`; the load draws select a band trajectory (p10/p50/p90) from the `Forecast.bands`.
- `robust_rerank` (extended): for each joint scenario, **materialize that scenario's load band** (write the chosen p-level series through the existing JSON seam) and build its plant prototxt, then run the **K finalists** → **K×J** EnergyPlus weeks. The existing **worst-case inlet feasibility (feasible in every joint scenario) + CVaR_α energy** selection runs over the joint ensemble. Confidence bands in the recommendation become the spread over the joint ensemble.
- Cost: K×J full-week runs on finalists only (e.g. 5×6 = 30/plan), bounded and surfaced (`n_scenarios`/`J` in the robust block). Plant-only behavior is preserved when no load bands are supplied (J degenerates to the plant ensemble).

---

## Data flow (end to end)

```
SeasonalForecaster.forecast(week_start, n_steps)
  → Forecast{ workload_schedules=p50, bands={p10,p50,p90}, weather_file=<real EPW>, week_start, method="seasonal" }
  → search (BeamPlanner) uses p50 point load + the per-forecast weather → finalists
  → robust_rerank over K×J joint (plant, load-band) scenarios
       (each scenario: materialize its load band + build plant prototxt + set weather_file)
       → worst-case feasibility + CVaR_α → robust winner + joint confidence bands
  → build_recommendation (schema 1.2: forecast bands + weather source + robust block)
  → UI (Forecast card + Confidence Bands)
Deploy: same forecaster (p50) + same real weather_file.
```

## Error handling & edge cases

- **Thin climatology buckets** → hour-of-day pooling → global mean (documented `MIN_BUCKET_SAMPLES`).
- **Week outside EPW coverage** → explicit error or logged fallback to static TMY (no silent wrong-weather).
- **Year-boundary weeks** (Dec→Jan) → RunPeriod Begin/End year set explicitly; day-of-week aligned.
- **Backward compatibility:** `method="persistence"` unchanged; no `weather_file` → static IWEC TMY; no `bands` → schema unchanged + P2b plant-only; `"seasonal-naive"` remains a persistence alias (deprecated).
- **Flat-load caveat** is acknowledged: the backtest reports the (likely modest) MAPE/RMSE gain honestly; the diurnal-shape + calibrated-band improvements are the substantive wins.

## Testing

- **Unit:** climatology fit + bands + thin-bucket fallback (synthetic data with a known seasonal pattern); persistence baseline parity; backtest metrics (MAPE/RMSE/PICP) on synthetic; weather seam (`write_week_config` sets `weather_file`; year/cross-year/day-of-week alignment; coverage validation); joint scenario construction + `robust_select` over joint ensembles; recommendation schema 1.2; UI Forecast card.
- **Integration (Docker, deselected by default):** one plan on a real week within Nov 2024–Jan 2025 using the seasonal forecast + the **real provided EPW** + a small joint-scenario robust re-rank on a 1-day window; assert it runs the real dates against the real weather and produces a schema-1.2 recommendation with bands.

## Open tunables (defaults)

- Climatology bin = 15-min (fallback hour-of-day); `MIN_BUCKET_SAMPLES` = 4.
- Backtest holdout = last 14 days; PICP target ≈ 0.80.
- Joint scenarios J = 6 — a curated set spanning plant {nominal, fouled, degraded} × load {p10, p50, p90}, weighted toward the correlated stress case (degraded plant + p90 load); matches the FC example list. α = 0.8 (inherited from P2b).
