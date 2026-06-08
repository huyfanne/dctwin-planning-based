# Setpoint Invariance — Root Cause & Fix

- **Date:** 2026-06-08
- **Reporter symptom:** every weekly recommendation returns the same setpoints — SAT 20 °C, airflow 4.8/13.8 kg/s, CHWST 13 °C — regardless of grid / beam / levels / days, for the Nov 2024 – Jan 2025 period.

## 1. Investigation (evidence)

From a real 125-candidate run (`runs/gds-2024-12-01-3d6342`), per-candidate EnergyPlus output:
- The safety-binding constraint is **max ITE inlet across the 22 1F-2A racks ≤ 26 °C**. That max is **ITE-16 = 43.64 °C, *bit-identical* across all 125 candidates**.
- Facility electricity varies only **9.448e9 → 9.455e9 (~0.07 %)**; ITE-1's inlet moves a mere 0.26 °C.
- ⇒ the setpoints have **~zero effect on both the binding constraint and energy**. EnergyPlus is deterministic, so identical candidates ⇒ no information for the search.

A 4-way parallel code/model investigation (actuator wiring, model coupling, objective/search, load magnitude) converged:

## 2. Root cause (definitive, file-grounded)

**The EnergyPlus model wires the binding sensor to be control-invariant.** Every `ELECTRICEQUIPMENT:ITE:AIRCOOLED` rack uses `Air Inlet Connection Type = AdjustedSupply`:

```
T_inlet = RecircFrac · T_zone + (1 − RecircFrac) · T_supply
```

but the per-rack **recirculation curve is a hard constant 1.0** — `building.idf:14293` (ITE-16: `Coefficient1 Constant = 1`, all other coeffs 0), and **all 22 1F-2A racks** (28 building-wide). With `RecircFrac = 1.0`, the `(1−RecircFrac)·T_supply` term is multiplied by **zero** → `T_inlet = T_zone` exactly. The SAT actuator (which sets `T_supply`) lands in a dead branch; airflow/CHWST act only on the zone heat balance and are swamped. CPU power is a loading-only curve, so IT heat is fixed by the forecast (hence the 0.07 % energy spread).

**Consequence chain:** all candidates infeasible (43.64 ≫ 26) → `objective.score` returns `+inf` for all (no least-violation tiebreak) → the beam keeps the lexicographic-first point → `pipeline.py:109` emits the hardcoded `infeasible_fallback` `Setpoints(sat.lb, flow.ub, chwst.lb)` = (20, 13.8, 13). Identical every run.

**Secondary findings (real, not the headline):**
- ACU on/off **masking** zeros ACU-16's setpoints for ~29 h (the `fan_on_off` schedule replays from index 0 each episode; `week_config` shifts only the RunPeriod). Candidate-independent, and moot while recirc = 1.0.
- The objective has **no least-violation tiebreak**, and the fallback corner is hardcoded.
- **Load is exonerated:** 1F-2A is 2.0 MW design / ~0.97 MW operating (loading ≈ 0.49) — realistic.

## 3. Fix

### 3a. Model recouple (decisive) — `scripts/recouple_ite_recirc.py`
Set the 22 `data hall 1f 2a ite-N recirculation …` BIQUADRATIC curves' `Coefficient1 Constant` from **1 → 0.10**, so `T_inlet` tracks the cooled supply. **0.10 = a reasonable contained-hall default (~90 % of the inlet follows supply); CALIBRATION ASSUMPTION flagged for later** — recalibrate against measured rack-inlet data. The IDF is gitignored, so the change lives in a tracked, idempotent script (one-time backup `building.idf.recirc_orig`; `--restore` reverts).

**Verification:** `scripts/spotcheck_recouple.py` runs two real EnergyPlus candidates (SAT 20 vs 26); recoupled ⇒ ITE-1 inlet drops markedly at SAT 20 (vs the 0.0 °C pre-fix spread).

### 3b. Planner guardrail (`beam_search.py`, `pipeline.py`, `recommendation.py`)
- **Degeneracy detector:** when the coarse sweep shows inlet spread < 0.1 °C **and** energy spread < 1 %, set `PlanResult.degenerate_no_signal` + surface it in the recommendation (schema **1.6**) — so a control-invariant model reads "setpoints had no measurable effect," not a confident corner.
- **Principled fallback:** replace the hardcoded corner with the (previously dead) `safest_fallback()` over the evaluated coarse grid (fewest inlet violations, then least energy).
- **Does NOT weaken the hard inlet cap** — the defect was a control-invariant sensor, not a too-strict constraint.

### 3c. Deferred (filed, not blocking)
Schedule-offset alignment + neutralizing on/off masking on the controlled hall (or excluding masked-off units from the safety max); re-enable the commented-out actuated-component existence check (`parser.py:587-591`); optional migration to `FlowControlWithApproachTemperatures`.

## 4. Status
Guardrail (3b) committed with TDD. Model recouple (3a) applied via the tracked script + verified by the spot-check. Calibration of the 0.10 fraction against measured inlets is the open follow-up.
