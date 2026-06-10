# Review: Digital Twin Dual-Loop Control Framework — After 1st Draft

**Date:** 2026-06-06
**Scope:** Double-check the implemented framework against the original workflow in
`/mnt/lv/home/hoanghuy/newcode/optimization-plan.jpg` and the design spec
(`docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md`).
**Method:** 12-agent infrastructure audit + 5-agent file-grounded framework audit, cross-checked
against the spec's locked decisions / non-goals / future work.
**Objective being assessed against:** a Digital Twin deployment for **weekly operation** with
**high-fidelity recommendations**.

---

The plan image is a **two-loop** system: an **inner planning loop** (Digital Twin = Forecaster +
EnergyPlus ↔ Planner = safety-filtered heuristic search) and an **outer deployment loop**
(System Data → Twin → Planner → Pre-validation → Expert Supervision → Authorized Commands → DC →
back to System Data).

**Headline: the inner loop is fully built and verified; the outer loop is built up to the expert
gate, then stops short of real closure.**

## 1. Component-by-component status

| Plan component | Status | Notes |
|---|---|---|
| **Data Center System** (physical) | 🔵 By design | Simulation-only: EnergyPlus *is* both twin and plant (locked decision). No real DC. |
| **System Data** (telemetry feedback) | ❌ Not impl. | No ingestion of real sensor/PDU data. The twin runs on forecasts, never reconciled to reality. |
| **Forecaster** (workload/weather) | 🟡 Partial | Workload = statistical persistence/seasonal-naive ✅. **Weather = static TMY window**, not a real forecast (`recommendation.py` hardcodes `"weather":"TMY-window"`). No ML, no retrain. |
| **EnergyPlus prediction** (temp/humidity/energy/equipment) | ✅ / 🟡 | Temp field, HVAC energy, PUE, inlet RH ✅ (`planner/kpi.py`). **Humidity = inlet RH only** (no zone/coil RH); **equipment status (chiller/tower/pump/fan on-off) not surfaced** despite being a twin output in the diagram. |
| **Planner — heuristic search** | ✅ / 🔵 | Best-first coarse-to-fine **beam search** ✅ (`planner/beam_search.py`). **But it searches a *constant* weekly setpoint trio (3 vars → 45 actuators), not time-varying "control sequences"** as the diagram's tree implies. Constant-setpoint is an explicit v1 non-goal; the `recommendation.json` schema leaves room to generalize. |
| **Objectives** (energy / temp / constraints) | ✅ | `energy + λ_T·inlet_excess + λ_R·rh + λ_Z·zone_band`, energy-dominant (`planner/objective.py`). |
| **Safety filter** (unsafe actions filtered) | ✅ | Hard-reject on inlet > 26 °C (0 tolerance) + soft penalty. RH is **soft-only** (`rh_hard=False`). |
| **Pre-validation** | ✅ | `planner/prevalidation.py` + `planner/validation.py`: KPI report vs baseline, PASS/FAIL on energy-reduction + 0 violations. |
| **Expert Supervision** | ✅ / 🟡 | Web app: operator/expert roles, approve/reject, **edit setpoints**, KPI review, 3D twin, history ✅. **"Real-time monitoring" shows the *planned/forecast* state, not a live telemetry stream.** |
| **Strategy Deployment / Authorized Commands** | 🟡 Orphaned | `planner/deploy.py` exists + unit-tested (sim-only, gated on `approved`), **but it's not wired into the web app — there is no `POST /api/plans/{id}/deploy` endpoint**. BMS adapter is a documented stub by design. |
| **Loop closure** (realized → next forecaster) | ❌ Not impl. | `deploy()` records `realized_kpis` but **nothing feeds them back** to `his_data`/the forecaster. The inner loop closes; **the outer loop does not.** |

## 2. Why the gaps exist
- **Simulation-only, constant-setpoint, statistical-forecaster, BMS-stub** were all **deliberate v1
  locked decisions / non-goals** (spec §2–3). These aren't oversights.
- **Loop closure + `/deploy` endpoint + realized-vs-predicted reconciliation** are **genuine
  unfinished work** — the spec §9 *claims* "realized System Data feeds the next week's forecaster,"
  but no code path implements it. This is the one place the build diverges from its own design.

## 3. Key issues (current code, file-grounded)

**Correctness / safety**
- **Edited setpoints aren't re-evaluated** — `PATCH /setpoints` updates the trio but keeps **stale
  `predicted_kpis`**; an expert could deploy wrong numbers. (medium)
- **`infeasible_fallback` is opaque** — when all candidates violate (happens at coarse `grid=2` with
  the forecast load), it silently returns the coolest corner with **no per-candidate failure
  diagnostics**. (medium)
- **No runtime safety re-check** before "deploying" — feasibility is search-time only; a
  weather/workload shift between approval and the week isn't re-validated.

**Fidelity**
- **Twin == plant, never calibrated** to real telemetry → predicted ≈ realized only because both are
  the same sim. This is *the* fidelity gap for the stated objective.
- **No uncertainty** on KPIs (point estimates only); no robustness to forecast error.
- **Static TMY weather**, stateless forecaster (no retrain on outcomes).

**Robustness / ops**
- **ProcessPool-in-threaded-uvicorn** fragility under concurrent plan submissions.
- **Cost**: ~245 full-week E+ runs/plan × minutes each; needs budget/parallelism management.
- Status is a free string (no enum/transition guard); broadcast 3→45 order assumed (no runtime
  assert); no per-candidate provenance log; no Docker integration test in CI; year-wrap weeks
  rejected.

*(Already fixed during the review session: the `dt_config` job crash, the `/progress` inf-→500, the
10 s/candidate post-process sleep, and per-evaluation live progress.)*

**What's solid:** the entire inner loop (forecast → beam search → EnergyPlus oracle →
recommendation), the pre-validation + approval gate, the web app, the verified full-building 3D
view, and **116 backend + 51 frontend tests**. M7 acceptance demonstrated **11.4% HVAC energy cut,
0 violations**.

## 4. Verified per-hall infrastructure (audit reference)

The model is a vertical stack of 7 halls/rooms; shared plant = **1 chiller, 1 cooling tower, 3 pumps**.
28 air loops total (one ACU per ITE object); **only 1F 2A's 22 ACUs are agent-controlled** (rest run
scheduled at 23 °C).

| Hall | Level | ACUs | Agent-controlled | IT power | ITE (objs · units) |
|---|---|---|---|---|---|
| GF 1A | GF | 1 | 0 (sched 23°C) | 4.00 MW | 1 · 1,000 |
| GF 1B | GF | 1 | 0 | 4.00 MW | 1 · 1,000 |
| **1F 2A** | 1F | **22** | **22** (+1 CHWST) | 2.00 MW | 22 · 22,000 |
| 1F 2B | 1F | 1 | 0 | 2.00 MW | 1 · 1,000 |
| 2F 3A | 2F | 1 | 0 | 4.00 MW | 1 · 1,000 |
| 2F 3B | 2F | 1 | 0 | 4.00 MW | 1 · 1,000 |
| Super Core 1F | 1F | 1 | 0 | 0.35 MW | 1 · 1,000 |

*(building.json carried stale IT-power figures for 3 halls; the IDF + room2ite values above are
authoritative.)*

## 5. Suggested next steps (toward weekly-operation deployment + high fidelity)

**P1 — Close the outer loop (deployment-readiness)**
1. **Wire `deploy()` into the web app**: `POST /api/plans/{id}/deploy` (expert) → run the sim plant
   week → store `realized_kpis` → status `deployed`; add a **realized-vs-predicted** panel.
2. **Feed realized data back**: append the deployed week's outcomes to `his_data` and refit the
   forecaster → actually close the diagram's loop.
3. **Re-evaluate edited setpoints** (recompute KPIs before approve/deploy); make `status` an enum
   with validated transitions.

**P2 — Raise recommendation fidelity** *(the core objective)*
4. **Twin calibration / `perturbed-plant` mode**: until real telemetry exists, run twin ≠ plant to
   *measure* robustness to model mismatch; design the telemetry-ingestion + calibration path so real
   BMS data can tune the model.
5. **Real forecasts + uncertainty**: integrate an actual weather forecast (replace static TMY) and a
   better workload forecaster; carry **confidence bounds** and select setpoints **robustly** (e.g.,
   worst-case over forecast scenarios) so 0-violations holds under forecast error.
6. **Finer control**: enable the **time-block (day/night) schedule** the schema already allows, and
   consider **per-hall setpoints** instead of one global trio — both lift energy savings and fidelity.

**P3 — Robustness & ops hardening**
7. **Search**: failure diagnostics + adaptive grid (auto-refine / start at grid ≥ 3 to avoid spurious
   `infeasible_fallback`); per-candidate provenance logging.
8. **Execution**: move planning to a dedicated worker/queue (not ProcessPool-in-thread); cap
   concurrent plans; materialize the forecast once per plan.
9. **CI**: add a marked 1-day real-EnergyPlus integration test (skip if no Docker).
10. **Real BMS adapter** behind the `deploy()` stub + a runtime safety gate before commands are
    applied (for the eventual hardware step).

**Bottom line for the objective:** you can already produce a deployable weekly setpoint
recommendation an operator applies by hand. To reach *automated weekly operation with high-fidelity
recommendations*, the two decisive investments are **(P1) closing the deploy→realize→refit loop** and
**(P2) twin calibration + forecast realism + uncertainty** — the inner optimization engine
underneath is sound.
