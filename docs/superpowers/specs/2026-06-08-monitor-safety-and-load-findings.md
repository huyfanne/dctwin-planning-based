# Monitor-Safety Review, recirc Calibration Gap, & Load-Alignment Findings

- **Date:** 2026-06-08
- **Companion to:** `2026-06-08-wellposed-objective-and-load-alignment-design.md`
- **Scope:** the *review/analysis* deliverables (Parts C & D) — what changed in code is the
  seasonal-forecaster switch + the recirc sweep script; the rest is verified findings.

---

## 1. Monitor-safety review — the ≤26 °C cap reads the correct signal (NO gap)

The premise to check was "the oracle monitor reads zone temps, not per-rack ITE inlet." Tracing
the signal end-to-end shows the opposite — the hard cap is on the **true per-rack ITE inlet
dry-bulb temperature**:

- `monitor.py:31` collects observations matching `"inlet dry-bulb temperature"` (the EnergyPlus
  `ITE Air Inlet Dry-Bulb Temperature` output of each `ElectricEquipment:ITE:AirCooled`), scoped
  to the controlled hall at `monitor.py:41`.
- `oracle_worker.read_step_sample` reads those into `StepSample.inlet_temps`.
- `kpi.py:64-67` takes `max(inlet_temps)` per step and counts `inlet_violation_steps` when it
  exceeds `inlet_cap` (26 °C).
- `objective.is_feasible` (`objective.py:38`) hard-rejects any candidate with
  `inlet_violation_steps > 0`; the robust gate adds a k·σ margin on top.

**Zone temps are a separate channel** used only for the soft 32 °C band penalty (`kpi.py:81-82`),
and the zone classifier explicitly excludes inlet sensors (`monitor.py:34-38`). So there is no
coverage gap and no zone-vs-inlet confusion.

**One real caveat:** the inlet *value* is computed by EnergyPlus's `AdjustedSupply` recirculation
formula `T_inlet = recirc·T_zone + (1−recirc)·T_supply`, so the cap is only as accurate as the
recirc=0.10 assumption (see §2). The *signal* is right; its *calibration* is the open item.

## 2. recirc calibration — not feasible on current data (data gap documented)

- recirc=0.10 is set in `scripts/recouple_ite_recirc.py` (→ the 22 1F-2A ITE recirculation curve
  constants in `building.idf`). It models ~90% containment — a reasonable default, not measured.
- **No measured per-rack inlet temperatures exist** in the repo: `his_data_processed.csv` is power
  / PDU / supply-temp telemetry only. So recirc cannot be fit to measured rack inlets today.
- The output-residual calibrator (`calibrator.py`) tracks aggregate KPI residuals, not per-rack
  inlet physics. Its prior history was a single synthetic cold-start week; that history was reset
  to clean cold-start when the energy scope changed (see the design spec §4.3).
- **What we ship instead:** `scripts/recirc_sensitivity.py` sweeps recirc ∈ {0.05, 0.10, 0.15,
  0.20} on one fixed setpoint and records inlet_max + hall-scoped energy → `2026-06-08-recirc-
  sensitivity.md`, quantifying how much the safety margin / setpoint choice depends on the
  assumption. **Calibration path when data exists:** install per-rack inlet sensors → accumulate
  paired (oracle inlet, measured inlet) weeks → fit the residual → adjust the curve constant.

## 3. Load alignment — mechanism fixed (seasonal); load is genuinely flat in the data

**Mechanism (fixed):** the live forecaster was `persistence`, which replays the last n_steps of
history regardless of `week_start` (`forecaster.py:19-25,113`) — so every planned week simulated
the same IT-load profile. Production is now re-fit to `seasonal` (`SeasonalForecaster`), whose
load is a (weekday × time-of-day) climatology **indexed to the target week** (`forecaster.py:142-
159`) and which carries p10/p50/p90 bands for the robust layer. Regression test
`test_seasonal_load_is_week_start_aligned_unlike_persistence` proves seasonal is week_start-aware
while persistence is not.

**Empirical reality (measured from `his_data_processed.csv`, 1F-2A IT loads, Nov 2024–Jan 2025):**

| component | variation |
|---|---|
| overall | mean 971 W, std 44 W (~4.5%) |
| weekly means | 952 → 982 W across the whole season (~3%) |
| day-of-week means | 967 → 975 W (~1%) |
| hour-of-day (diurnal) | 897 → 1035 W (~14% swing) |

So the 1F-2A IT load has **no meaningful seasonal trend and almost no weekday pattern** — the only
real structure is the ~14% diurnal swing. Consequences:

- The seasonal switch correctly aligns the **diurnal phase** to the calendar week and makes the
  load **week_start-aware in principle** (weeks starting on different weekdays differ).
- But two weeks starting on the **same weekday** (e.g. Nov 11 & Dec 16 2024, both Mondays) are
  legitimately near-identical in load — there is no seasonal signal to separate them. This is
  faithful to the data, not a bug; manufacturing a difference would invent signal.
- **Weather remains the dominant week-to-week driver** (different `RunPeriod` → different ambient),
  which — post-recouple — now flows through to the setpoints. To make a forecast vary by calendar
  *season* (not just weekday phase) one would need multi-year history or a calendar-indexed model;
  with one flat season that is not warranted.
