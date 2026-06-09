# G1/G2/G3 — Load Alignment, Recirc Sensitivity, Energy Forensics

- **Date:** 2026-06-09
- **Scope:** `planner/forecaster.py` (G1 code change); investigation + docs for G2/G3.
- **Status:** G1 implemented (TDD, full suite green); G2 diagnosed + documented; G3 reconciled.

Three follow-ups raised after the well-posed-objective work, each verified against real
EnergyPlus / the run artifacts before acting.

---

## G1 — Align the IT load to the calendar week  ✅ implemented

**Root cause (verified, not assumed).** The "schedules replay from index 0, same load every
week" premise was **already obsolete**: the live forecaster is `seasonal`, and
`seasonal_climatology` keys every step on `(weekday × time-of-day)` starting at `week_start`,
so the materialized array begins at `week_start` and the sim reads index 0 = `week_start`.
Empirically (`materialize()` diff): a Monday-start week ≠ a Thursday-start week. The genuine
residual gap was that two *different calendar weeks with the same start-weekday came out
byte-identical* (Nov-11 Mon == Dec-16 Mon) — the pooled climatology carries the diurnal/weekly
**shape** but not the slow month-to-month **level** drift.

**Is there a signal to align to?** The raw 1F-2A load is **empirically flat**: monthly means
Nov 963.8 → Dec 974.0 → Jan 976.0 kW = **1.26% month-to-month** (CoV 4.5%, mostly intra-day).
So "two weeks differ only by weather" is *physically correct* for this steady colo load — not a
bug. The fix makes the small real drift show up rather than inventing variation.

**Implementation.** `calendar_level_scale(loading, times, week_start, window_days=10)` returns
`mean(load in a ±window_days window around week_start, clamped to the data span) / mean(load)`,
computed from **whole-day means** (diurnal-phase invariant, so level-stationary data → exactly
1.0). `SeasonalForecaster.forecast` multiplies the pooled climatology (point + p10/p50/p90
bands) by this scale and re-clips to [0,1]. Effect:
- Different calendar months now produce different load levels (Nov < Dec < Jan), tracking the
  real ~1.3% drift, while the **diurnal/weekday shape is preserved** (normalized shape identical).
- A future week (beyond the data) clamps to the most recent window's level — honest persistence,
  no trend extrapolation.

**Honest magnitude.** ~1.3% — weather still dominates week-to-week. The mechanism is now correct;
the data simply has little seasonal load signal.

**Tests** (`tests/test_forecaster.py`): `calendar_level_scale` tracks period / clamps
out-of-range / is unity on flat history; the seasonal forecast now differs by calendar month and
preserves the diurnal shape. Full unit suite green (regression in
`test_backtest_forecaster` fixed at root cause — the level is computed from whole-day means so
perfectly-periodic data is left untouched, not by weakening the assertion).

---

## G2 — Recirc calibration + monitor coverage/safety review  ✅ diagnosed

**Monitor safety — no gap.** The hard inlet cap (≤ 26 °C) is evaluated on the **true per-rack
ITE inlet** (`ITE Air Inlet Dry-Bulb Temperature`), classified separately from zone air temp in
`monitor.discover_monitor` and read into `StepSample.inlet_temps`; `aggregate_kpi` takes the max
over those per-rack inlets. Zone temps drive only the softer 32 °C band penalty. The cap reads
the correct signal.

**Recirc is currently INERT** (see `2026-06-08-recirc-sensitivity.md`). Two real-E+ sweeps show
the inlet/energy are bit-identical across recirc **0.05–0.50** at both flow 4.8 and 9.3. So:
- Calibrating 0.10 is **moot today** — it has no effect to tune.
- The model effectively assumes **near-perfect containment**; the inlet safety margin is
  therefore **optimistic** vs a real hall with imperfect aisle separation.
- Right next step is **not** a blind recalibration: first make recirculation a live lever (the
  `AdjustedSupply` zone-reference wiring), then fit it to **measured per-rack inlets** — which do
  not exist in `his_data` (power/PDU/supply-temp telemetry only). Until then keep 0.10 as a
  documented placeholder and rely on the hard cap + robust margin.

---

## G3 — Predicted 697 343 vs Baseline 450 kWh  ✅ reconciled

Run `gds-2024-12-15-51e793`, **schema 1.4 (pre-fix)**:
- **697 343 kWh** = the *old facility-wide* HVAC scope (`total_power − it_power`, ~14.5 MW over
  2 days) — the controlled hall is only ~5–7 MW; the metric reported the whole facility.
- **450 kWh** = a **hardcoded frontend placeholder** (`BASELINE_KPIS` in `Review.tsx`), never
  computed.

Both were already fixed by commit `83e83d84`: energy scoped to the hall (`hall_controllable_v1`),
a real as-operated baseline computed on the same metric (schema 1.7 `baseline` block), and the
placeholder removed (only a test asserting its absence remains). Confirmed live: a full
beam-search plan returns predicted 261 122 vs baseline 269 688 kWh (+3.18%), apples-to-apples.
The "CRAH airflow always 4.8 kg/s" is a *genuine* optimum (lowest fan power, feasible), not a
collapse — the same plan picks SAT 24.5 / CHWST 19.0 off the bounds.

---

## Residual / follow-ups
- Make recirculation a live, calibratable lever (G2) — needs the `AdjustedSupply` wiring fix +
  eventually measured per-rack inlets.
- Calendar-level drift is small because the load is flat; revisit if a future dataset shows real
  seasonal load variation.
