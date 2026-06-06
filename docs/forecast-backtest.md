# Forecast backtest result (2026-06-06)

Backtest of the FA `SeasonalForecaster` (day-of-week × time-of-day climatology + p10/p50/p90
bands) vs the existing persistence baseline, on the real telemetry
`data/his_data_processed.csv` (72 days, 15-min), 14-day holdout, via
`python -m planner.backtest_forecaster`.

| Room | RMSE seasonal | RMSE persistence | MAPE seasonal % | MAPE persistence % | PICP (p10–p90) |
|---|---|---|---|---|---|
| GF 1A | 0.0279 | **0.0043** | 4.44 | **0.61** | 0.05 |
| GF 1B | 0.0300 | **0.0075** | 4.70 | **1.08** | 0.09 |
| 1F 2A | 0.0387 | **0.0064** | 7.03 | **1.09** | 0.07 |
| 1F 2B | 0.0262 | **0.0203** | 7.54 | **5.65** | 0.38 |
| 2F 3A | 0.0311 | **0.0071** | 4.67 | **0.98** | 0.09 |
| 2F 3B | 0.0494 | **0.0075** | 5.30 | **0.70** | 0.07 |
| Super Core 1F | 0.0032 | **0.0007** | 0.67 | **0.13** | 0.35 |

**Result: persistence beats seasonal on all 7 rooms; band calibration is poor (PICP ≈ 0.16, target ≈ 0.80).**

## Why

The GDS loads are ultra-flat and low-utilization (~0.06–0.1% of nameplate) with a slow level
drift over the 72-day window. Persistence (last 14 days) sits adjacent to the holdout's level
and tracks it almost exactly. The seasonal climatology, by taking the median over the whole
58-day training window, imposes a diurnal/weekly *shape* that is mostly noise relative to the
near-constant reality, and its empirical p10–p90 bands — honest about the tiny within-bucket
spread — are far too narrow to cover the train→holdout level drift.

## Decision

- **Production default stays `persistence`** (the production `models/forecaster.pkl` keeps
  `method="persistence"`). Do NOT switch the default to `"seasonal"` on this data.
- The `SeasonalForecaster` + `backtest_forecaster` remain in the codebase (selectable via
  `method="seasonal"`); the backtest is the gate that decides — re-run it if/when loads become
  more variable/utilized (e.g. new workloads, higher occupancy), and switch the default only if
  seasonal then wins with PICP near target.
- **Forecast realism FC (load-uncertainty → P2b joint scenarios) is DEFERRED**: the load bands
  are not trustworthy on the current flat data, so load-perturbed scenarios would be degenerate.
  Revisit alongside a re-backtest once load variance materializes.
- **Forecast realism FB (per-forecast real weather) proceeds**: it is a genuine, data-independent
  fidelity improvement (real ambient conditions drive cooling load), unaffected by this finding.
