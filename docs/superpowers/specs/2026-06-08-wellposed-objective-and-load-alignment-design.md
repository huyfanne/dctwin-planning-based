# Well-Posed Objective, Real Baseline, Week-Aligned Load, recirc Sensitivity — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved design (3 forks decided by operator) — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Builds on:** `2026-06-08-setpoint-invariance-rootcause-design.md` (the recouple fix that made the inlet respond to SAT). This spec fixes the *energy* side, the *baseline*, the *load alignment*, and documents the *recirc* uncertainty.

---

## 1. Problem statement (verified root causes)

1. **Energy objective is facility-wide while only the 1F-2A hall is controlled.** `aggregate_kpi` sums `hvac_w = total_power_w − it_power_w` (`kpi.py:58`) from the **facility-wide** `"total power"`/`"total it power"` observations (`monitor.py:18-21`). 1F-2A is ~1 of 7 halls, so setpoint changes move the metric <1% — below the EnergyPlus run-to-run noise floor. The search has no usable gradient → flow (and previously every setpoint) collapses to a bound. The thermal KPI is already correctly hall-scoped (`monitor.py:39-43`); only energy is not.
2. **"Baseline 450 kWh" is a hardcoded frontend placeholder** (`frontend/src/pages/Review.tsx:30-36`), never computed. `baseline_energy_kwh` is `None` in every run → `energy_reduction_vs_baseline_pct` is null. The displayed gap is meaningless.
3. **IT load does not shift with `week_start`.** Live forecaster is `persistence` (`models/forecaster.pkl`), which replays the **last n_steps of history** (`forecaster.py:19-25,113`) regardless of `week_start`. The `seasonal` forecaster already aligns by (weekday × time-of-day) climatology to the target week (`forecaster.py:58-69,142-159`) but is not the live default.
4. **recirc=0.10 is an uncalibrated assumption** and there is no measured per-rack inlet data to fit it (`his_data` is power/PDU only; `calibration.json` is a 1-week cold start with a +4.19 °C inlet bias). The monitor-safety review found the ≤26 °C cap **is** correctly evaluated on the true per-rack ITE inlet dry-bulb temp (NOT zone temp) — no safety gap; accuracy is bounded only by recirc.

## 2. Decisions (operator-approved)

- **Energy scope:** controllable HVAC = **Σ(22 1F-2A ACU fan power) + full chiller/CHW plant power** (5 chillers + 5 CHW pumps + condenser-water pump + 5 cooling-tower fans). Cross-candidate variation is then entirely from the 1F-2A control actions (fans directly; chiller via SAT/CHWST), with the large fixed offsets (other-hall fans, lighting, IT) removed → strong S/N.
- **Baseline:** **as-operated current setpoints**, derived from `his_data_processed.csv`, evaluated once through the oracle on the planned week → real `energy_reduction_vs_baseline_pct`.
- **recirc:** keep 0.10 as a **documented assumption**; ship a **sensitivity sweep** {0.05, 0.10, 0.15, 0.20} + a monitor-safety review note. No model parameter change.

## 3. Goals / non-goals

**Goals**
- The optimizer minimizes a hall-scoped HVAC energy whose candidate-to-candidate variation is well above the noise floor, so setpoints (esp. flow) reflect a real energy/safety trade-off, not a degenerate corner.
- A real baseline + honest `energy_reduction_vs_baseline_pct`, surfaced in the UI (no fake 450).
- `week_start` changes the simulated IT load (week-aligned).
- recirc uncertainty quantified + documented; monitor-safety review recorded.

**Non-goals**
- Per-hall chiller attribution (operator chose full-plant scope — the argmin is unaffected by the fixed shared offset).
- Calibrating recirc to measured inlets (no data; deferred with a documented path).
- Changing the safety cap mechanism (review confirmed it is correct).

## 4. Sub-project A — Hall-scoped HVAC energy objective

### 4.1 Monitor (`planner/monitor.py`)
Add `hvac_power_names: list[str]` to `MonitorSpec`. In `discover_monitor(env, hall)` classify the controllable HVAC power observations:
- **Hall ACU fans:** name contains `hall` AND `"acu"` AND `"fan power consumption"`.
- **Plant (shared):** name matches any of — `"chiller" … "power consumption"` excluding `"chwp"` (compressor, Chiller Electricity Rate), `"chwp power consumption"`, `"cwp power consumption"`, `"cooling tower" … "fan power consumption"`.
- `hvac_power_names = hall_acu_fans + plant_power`. Keep `total_power_name`/`it_power_name` unchanged (still used for PUE). Raise `ValueError` if `hvac_power_names` is empty when a hall is given (fail-closed; never silently fall back to facility scope).

### 4.2 Sample + KPI (`planner/kpi.py`, `oracle_worker.py`)
- `StepSample` gains `hvac_power_w: float = 0.0` (sum of the `hvac_power_names` readings).
- `read_step_sample` (`oracle_worker.py:32-41`) sums `monitor.hvac_power_names` into `hvac_power_w`.
- `aggregate_kpi` (`kpi.py:58-59`) and `step_trajectory` (`kpi.py:106-110`): `hvac_w = smp.hvac_power_w` (the scoped sum) instead of `total_power_w − it_power_w`. PUE still uses `total_power_w / it_power_w`.
- **Back-compat:** when `hvac_power_w == 0.0` and the sample has total/it set (older/mock paths), fall back to `total_power_w − it_power_w` so existing unit tests + `mock_evaluator` keep working without per-component power.

### 4.3 Schema + calibration
- Bump `recommendation.json` schema 1.5 → **1.6**; add `energy_scope: "hall_controllable_v1"` so a reader knows `total_hvac_energy_kwh` is hall-scoped, not facility.
- The old `calibration.json` energy bias (341958 kWh) is facility-scale → invalid post-rescope. Reset the energy bias/sigma on first scoped run (or document a required re-fit). Inlet calibration is unaffected.

## 5. Sub-project B — Real as-operated baseline

### 5.1 As-operated setpoints (`planner/baseline.py`, new)
`as_operated_setpoints(his_data, cfg) -> Setpoints`:
- **SAT** = median of 1F-2A CRAH `*_AirSupplyTemperature` columns.
- **CHWST** = median of chiller `*_ChilledWaterSupplyTemperature` columns.
- **flow** = median CRAH `*_FanSpeed` (fraction) × design mass flow per ACU × n_acu, clipped to the search-space flow bounds. (Design flow from the model/config; if unavailable, fall back to the mid-range flow and log it.)
Column patterns are config-driven (extend the forecaster config) so they are not hard-coded to one site.

### 5.2 Wiring (`webapp/jobs.py`, `planner/pipeline.py`)
- In `run_plan_job`, after building the forecast, compute `baseline_sp = as_operated_setpoints(...)`, evaluate it once: `base_kpi = oracle.evaluate([baseline_sp], forecast)[0]`, pass `baseline_energy_kwh = base_kpi.total_hvac_energy_kwh` to `run_weekly_plan`.
- `build_recommendation` already supports `baseline_energy_kwh` → computes `energy_reduction_vs_baseline_pct`. Also record `baseline_setpoints` + `baseline_energy_kwh` in the artifact (schema 1.6).

### 5.3 Frontend (`frontend/src/pages/Review.tsx`, `Dashboard.tsx`)
- Delete `BASELINE_KPIS` placeholder (incl. `total_hvac_energy_kwh: 450`). Read the real `baseline_energy_kwh`/`baseline_setpoints` from the recommendation; show `energy_reduction_vs_baseline_pct`. Relabel the energy metric "Controllable HVAC energy (1F-2A + chiller plant)". If no baseline present (older runs), hide the comparison instead of faking it.

## 6. Sub-project C — Week-aligned IT load
- Re-fit the forecaster as `seasonal`: `fit_forecaster.py --method seasonal` → overwrite `models/forecaster.pkl`. Verify `his_data_processed.csv` has the `_time` column `SeasonalForecaster` needs (it does: col 1 `_time`) and ≥ `min_samples` per bucket.
- Add a regression test: two different `week_start`s with different weekday/seasonal position produce **different** workload arrays (persistence returns identical; seasonal must differ).
- Keep `persistence` available; just change the default the webapp ships.

## 7. Sub-project D — recirc sensitivity + monitor review
- `scripts/recirc_sensitivity.py`: for recirc ∈ {0.05,0.10,0.15,0.20}, set the curve constant (reuse `recouple_ite_recirc.py` logic), run a fixed mid-range setpoint through the oracle for one week, record inlet_temp_max + scoped energy → `docs/.../recirc_sensitivity.md` table. Shows how feasibility/setpoints move with the assumption.
- `docs/.../monitor-safety-review.md`: record that the ≤26 °C cap reads true per-rack ITE inlet dry-bulb (`monitor.py:31` → `kpi.py:64-67` → `objective.py:38`), zone temps soft-only, accuracy bounded by recirc.

## 8. Testing strategy (TDD; EnergyPlus mocked in unit tests)
- **A:** `discover_monitor` classifies ACU-fan + plant power into `hvac_power_names` (fake env with the real names); `aggregate_kpi` uses `hvac_power_w` when present and falls back to total−it when zero; `read_step_sample` sums the named powers. No real E+.
- **B:** `as_operated_setpoints` returns medians within bounds from a synthetic `his_data` frame; `run_weekly_plan` threads `baseline_energy_kwh` into the recommendation + computes reduction%. Frontend vitest: Review shows real baseline + reduction, no 450; hides comparison when absent.
- **C:** seasonal forecaster yields week-dependent arrays (unit test on two week_starts).
- **D:** the sweep script is integration-gated (real E+); unit-test the curve-set helper only.
- **Integration (docker-gated, hand-run):** one scoped plan shows energy variation across candidates ≫ prior 0.07% and a non-null reduction%.

## 9. Milestones
| # | Milestone | Verifies |
|---|---|---|
| **A1** | `MonitorSpec.hvac_power_names` + `discover_monitor` classification (+ tests) | scope discovery |
| **A2** | `StepSample.hvac_power_w` + `read_step_sample` sum + `aggregate_kpi`/`step_trajectory` use it w/ fallback (+ tests) | scoped energy |
| **A3** | schema 1.6 `energy_scope` + calibration energy reset/doc | artifact + calib |
| **B1** | `planner/baseline.py as_operated_setpoints` (+ tests) | baseline setpoints |
| **B2** | jobs.py/pipeline wiring: evaluate baseline once, thread reduction% (+ tests) | real baseline |
| **B3** | frontend: real baseline, drop 450, relabel (+ vitest, build) | UI honesty |
| **C1** | refit forecaster seasonal + week-alignment regression test | load alignment |
| **D1** | recirc sweep script + sensitivity doc + monitor-safety review doc | recirc uncertainty |

## 10. Reference file index
- `planner/monitor.py` (MonitorSpec, discover_monitor), `planner/kpi.py` (StepSample, aggregate_kpi, step_trajectory), `planner/oracle_worker.py` (read_step_sample), `planner/pipeline.py` (run_weekly_plan baseline), `planner/recommendation.py` (schema/baseline), `planner/baseline.py` (new), `planner/forecaster.py` (seasonal), `webapp/jobs.py` (wiring), `frontend/src/pages/Review.tsx`+`Dashboard.tsx` (baseline display), `fit_forecaster.py` (method), `scripts/recouple_ite_recirc.py` (curve-set reuse), `configs/dt/dt.prototxt` (power obs names).
