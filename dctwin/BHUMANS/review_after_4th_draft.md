# Review After the 4th Draft — Digital Twin Dual-Loop Control Framework

**Date:** 2026-06-12 · **Reviewed against:** the original plan (`optimization-plan.jpg`)
**Audience:** written for both lay readers (plain-language sections) and engineers (technical detail included).

---

## 0. One-paragraph summary (for anyone)

We built a **digital twin** — a physics simulation of a real data-center cooling system — wrapped in a
web application that recommends, every week, the cooling settings that **minimise energy without ever
letting any server's inlet air exceed 26 °C**. Since the 3rd draft, the system stopped being "a strong
simulator" and became a **measured, learning control loop**: six consecutive weekly cycles were planned,
safety-gated, expert-approved, deployed and measured. The twin's weekly-energy prediction error shrank
from **1.33% to ~0.1%**; energy savings ramped from **0% to 3.6%** — released stepwise by a safety gate
exactly as fast as measured confidence allowed; and **zero safety violations** occurred (worst realised
inlet 25.6 °C vs the 26 °C cap). The webapp now includes **live telemetry monitoring** (rack heat-map,
alerts, setpoint-compliance), deploys run in **shadow mode** (commands recorded, never actuated), and the
planner gained **weather-uncertainty hedging, tariff/carbon-aware optimization, physics re-calibration and
per-rack hotspot views**. The one thing that remains deliberately unbuilt is the physical connection to a
real building (BACnet/Modbus) — everything up to that seam is implemented, tested (422 backend + 104
frontend tests) and exercisable today against simulated-but-labelled data.

---

## 1. Scorecard vs the original plan

The plan describes a **dual-loop framework**: an inner *planning* loop (Forecaster → EnergyPlus physical
model → heuristic Planner with energy/temperature/constraint objectives, unsafe actions filtered) and an
outer *deployment* loop (Pre-validation → Expert Supervision with real-time monitoring/override →
authorized commands to the Data Center → System Data feeding back).

| Plan element | Status | Verdict |
|---|---|---|
| Forecaster — IT workload | ✅ | persistence + seasonal climatology + calendar-level alignment; p10/50/90 bands |
| Forecaster — weather | ✅ (upgraded) | historical-analog mean+σ for the target week; EPW variants; **+1σ hot-week scenario hedges the gate**; real-forecast-API seam documented |
| EnergyPlus physical model | ✅ | E+ 9.5 in Docker, BCVTB-coupled; full-week run per candidate; predicts per-rack inlets, zone T, RH, power |
| Heuristic search planner | ✅ | coarse-to-fine beam search over SAT/airflow/CHWST → 45 actuators; optional day/night blocks |
| Objectives (energy·temperature·constraints) | ✅ (extended) | energy **or time-of-use cost/carbon** (tariff seam); hard inlet ≤ 26 °C; soft RH/zone penalties |
| Unsafe-action filtering | ✅ | three nets: hard cap in search → robust worst-case ensemble (plant ±spread + hot weather) → zero-tolerance deploy backstop |
| Pre-validation | ✅ | independent nominal + worst-case replays; inlet trajectory artifacts in the UI |
| Expert supervision — evaluate/override/deploy | ✅ | approve/reject/edit-setpoints/deploy; role-gated (operator vs expert); blocked-unsafe is non-approvable |
| Expert supervision — **real-time monitoring** | ✅ **new** | Live page: 22-rack inlet heat-map, alerts (warn ≥25 °C, critical ≥26 °C), setpoint compliance, rolling charts, SSE |
| Authorized commands → real DC | 🟡 **shadow** | deploys expand to 45 per-actuator commands and are **recorded, not actuated**; BACnet adapter is an explicit `NotImplementedError` seam |
| System data feedback | 🟡 | telemetry store + `POST /api/telemetry` push seam + labelled simulated feed; calibration learns each deployed week — inputs are sim until a real collector connects |

**Bottom line:** every box of the original diagram is implemented; the loop is closed end-to-end in
software and *measured*, with one honest qualifier — "reality" is still a perturbed-plant simulation
standing in for the building, by design, until field access exists.

---

## 2. What has been implemented (with the technical details)

### 2.1 Inner loop — planning in physics
- **Oracle:** `ParallelEnvOracle` fans candidate evaluations across a `ProcessPoolExecutor`; each
  candidate is a **full-week EnergyPlus 9.5 run** (Docker, BCVTB socket coupling, host 172.17.0.1).
  Per-candidate watchdog (300 s) + batch deadline + **stall watchdog** (abandons stragglers if nothing
  completes within 1.5× timeout — added after a live incident where 2 lost futures froze a plan for an hour).
- **Search:** coarse grid (g³ over SAT 20–26 °C, flow 4.8–13.8 kg/s, CHWST 13–19 °C) → top-B beam →
  halving-step neighborhood refinement; degenerate-signal detection; `broadcast.py` expands 3 globals to
  **22 SAT + 22 flow + 1 CHWST actuators**.
- **Objective:** minimise weekly hall-scoped HVAC energy (`hall_controllable_v1` = 1F-2A ACU fans + shared
  chiller/CHW plant) **or, when `data/tariff.json` exists, the 24-hour-rate-weighted cost/carbon**
  (`WeeklyKPI.weighted_energy_cost`); soft penalties for inlet excess, RH excursion, zone band. Feasibility
  (safety) never trades against price.
- **Safety gate (the heart of the system):**
  1. *Hard cap in search:* any candidate with one 15-min step over 26 °C inlet is rejected; a k·σ margin
     (fading-floor calibration σ) pre-tightens the cap.
  2. *Robust ensemble:* finalists re-simulated on perturbed plants — ensemble **center = data-driven
     believed plant** (`data/plant_calibration.json`, fitted by the re-calibrator; DEFAULT_PLANT until then),
     width = empirical-Bayes posterior σ_post = √((n·s²+σ₀²)/(n+1)) clamped to [±2% floor, ±10% cold-start],
     **plus one hot-weather scenario** (dry-bulb +1σ of the historical-analog spread). Scenario KPIs are
     bias-corrected and tested against the *hard* cap (uncertainty single-counted — the margin belongs to
     the nominal check). If the energy optimum is fragile, a **safety ladder** substitutes the cheapest
     provably-robust alternative (chilled-water-first — the cheap axis — before airflow), instead of blocking.
  3. *Deploy backstop:* a realised week with any inlet violation → `deploy_blocked`, never `deployed`.
- **Live recirculation (fidelity):** `planner/recirc.py` — recirc fraction estimated from measured rack
  inlets via the mixing identity r=(T_in−T_sup)/(T_ret−T_sup); flow-shortfall model raises r when CRAH
  airflow undershoots ITE demand; conservative-only inlet correction; `fit_recirc.py` calibrates
  `data/recirc.json` (a provable no-op until calibrated — no invented constants).

### 2.2 Outer loop — deploy, measure, learn
- **Shadow-mode BMS:** `ShadowBmsAdapter.apply()` writes the 45 per-actuator commands
  (`runs/<id>/deploy/bms_commands.json`, `actuated:false`); rec stamped `deploy_mode:"shadow"`,
  `realized_source:"sim"` (schema 1.8). `BacnetBmsAdapter` is the explicit field seam.
- **Calibration:** after every deploy, paired (predicted, realized) KPIs update per-KPI **bias** and two
  uncertainties (fading-floor σ for the nominal margin; σ_post for the ensemble). Currently
  n_weeks = 7, bias_inlet ≈ 0.005 °C, σ_inlet(measured) ≈ 0.14 °C.
- **Physics re-calibration (#5):** persistent energy bias over ≥4 weeks fits a bounded fan-efficiency
  correction (winsorized realized/predicted ratios → factor clip [0.85, 1.15]) persisted to
  `data/plant_calibration.json` — the twin's *plant parameters* now learn, not just its outputs, and the
  fitted state becomes the robust ensemble's center (#9).
- **Operational state machine:** queued→running→pending_approval→approved→deploying→deployed (+ rejected,
  failed, infeasible_fallback, blocked_unsafe, deploy_failed, deploy_blocked, cancelled); duplicate-deploy
  race fixed (accept-time reservation + heal); orphan reconciliation on restart; cooperative cancel +
  wedged-run recovery tooling.

### 2.3 Webapp — the operator's cockpit (7 pages)
- **Live (new):** rack heat-map (22 ITEs), alert banner, KPI tiles, **commanded-vs-held setpoint
  compliance** (tolerance 0.5/axis vs the latest deployed plan), ranked **Rack Detail hotspot table**,
  30-min rolling chart, SSE stream + poll fallback, explicit **SIMULATED FEED badge**.
- **Dashboard / New Plan / Review / History / Digital Twin 3D / Login:** planning-context decks (past+
  forecast IT load & weather, previous-week setpoints), live search progress (SSE), KPI vs baseline with
  deltas, confidence bands, inlet trajectories (nominal + worst-case), predicted-vs-realised history trend,
  **3-D hall with rack rows live-colored from telemetry**, token auth (operator/expert, fail-closed).
- **API:** 21 endpoints incl. `POST /api/telemetry` (the historian push seam), `/api/live*`,
  `/api/planning-context`, plans CRUD + approve/reject/deploy/cancel + SSE streams.

### 2.4 Measured results (the 4th draft's defining evidence)
| Metric | Measured |
|---|---|
| Consecutive weekly cycles (plan→gate→approve→deploy→measure→learn) | **6** (weeks of 2024-11-08 … 12-13) |
| Twin weekly-energy prediction error | **1.33% → 0.86% → 0.21% → ~0.1%** |
| Inlet prediction error | **≤ 0.2 °C every week** |
| Energy saving vs as-operated baseline | **0% → 3.2% → 3.6%** (gate-released as σ shrank 1.0 → 0.43 °C) |
| Safety violations across all deployed weeks | **0** (worst realised inlet 25.60 °C) |
| Physical well-posedness (verified by real-E+ sweeps) | airflow moves hall energy **15.5%**, CHWST **3.4%**, SAT ~0.5% |
| Tests | **422 backend + 104 frontend**, all green; 9 Docker-gated integration tests |

### 2.5 Engineering quality
TDD throughout (test-first, never weakened); branch-per-feature with `--no-ff` merges; 20+ dated
spec/plan documents; schema-versioned artifacts (1.0→1.8, additive); knowledge graph (1,200+ nodes)
regenerated per merge; a committed **agent run-skill** (`/run-dctwin`: start/smoke/plan/screenshot/
unstick) so any future agent or engineer can drive the system reproducibly.

---

## 3. What is NOT implemented, why, and known issues

| Item | Status & why | Risk/issue |
|---|---|---|
| **Physical BMS actuation** (BACnet/Modbus/vendor API) | Deliberate: no field access on this rig. The seam is one class (`BacnetBmsAdapter`); shadow mode already produces the exact 45-command artifact a field adapter would write. | Until connected, "realised" KPIs come from the perturbed-plant simulation — the learning loop is *structurally* proven, not field-proven. |
| **Real telemetry source** | The push endpoint + store + dashboards exist; the feed is simulated (and labelled). A real historian collector is config, not code. | Sim feed values are plausible, not real; alerts/compliance UX is exercised but not field-validated. |
| **Recirculation calibrated to measured rack inlets** | The estimator + CLI exist; require real rack sensors. Default keeps the correction at zero (honest no-op). | Until calibrated, the inlet margin may be optimistic for halls with imperfect containment. |
| **Real weather forecast API** | Historical-analog σ is used (defensible short-horizon proxy); the provider seam is documented. | Analog σ understates synoptic extremes; the +1σ hot scenario partially compensates. |
| **Intra-week re-planning / mid-week override UI** | Out of scope for weekly cadence v1; cancel + re-plan covers urgent cases manually. | A sudden load/weather shift mid-week relies on operator vigilance (Live alerts help). |
| **Humidity as a controlled variable** | RH is monitored + penalized (optionally hard); no dehumidification actuator modeled in the IDF. | Low risk in this climate envelope; revisit if RH excursions appear in telemetry. |
| **E2E browser tests in CI** | Vitest + pytest cover units; the driver smoke + screenshots cover E2E manually. | CI cannot catch full-stack regressions automatically yet. |
| Known modeling caveats | 2-day vs 7-day energy scaling oddity in some historical runs (different metric scopes mixed in old artifacts — schema <1.7 rows show "—" by design); IT load nearly flat (~1.3%/month) so weather dominates week-to-week variation; absolute setpoints are directional until recirc is field-calibrated. | Documented in-product (UI notes) and in specs. |

---

## 4. Next steps (toward the stated goal)

1. **Field pilot, shadow first (the only remaining tier-A step):** point a real collector at
   `POST /api/telemetry`; implement `BacnetBmsAdapter` behind the existing seam; run **recommend-only for
   4–8 weeks** comparing predictions to real measurements; then enable actuation hall-by-hall.
2. **Calibrate recirc from the first real rack-inlet data** (`fit_recirc.py --write`) — directly de-risks
   the safety margin where it matters most.
3. **Swap the weather provider** behind `weather_forecast.weather_stats` to a real short-horizon forecast
   (e.g., met-service API) — everything downstream (variants, hot scenario) is unchanged.
4. **Populate `data/tariff.json`** with the site's actual time-of-use tariff or grid-carbon profile to
   switch the objective from kWh to $ / CO₂ where that is the operator's real target.
5. **Grow robustness with data:** as deployed weeks accumulate, σ_post tightens automatically and the
   re-calibrator re-centers the ensemble; consider raising n_scenarios for high-stakes weeks (already a
   plan parameter).
6. **Operator hardening:** alert webhooks (email/Slack), mid-week guided re-plan flow, per-ACU power
   telemetry when available, CI-managed E2E (the driver is already automatable).

---

## 5. Operational procedure (how an operator runs a week)

1. **Launch:** `scripts/clear-and-run.sh` (or the agent driver) → open :8001 → token login (operator/expert).
2. **Monitor:** Live tab — heat-map green, no alerts, compliance ✓ (data labelled SIMULATED until a real feed connects).
3. **Plan:** New Plan tab — defaults are sensible (week in coverage, grid 5/beam 3/levels 3); review the
   planning-context decks (past+forecast load & weather, last week's setpoints); launch; watch live progress.
4. **Review:** Review tab — predicted vs baseline KPIs with deltas, confidence bands, inlet trajectory vs
   the 26 °C line (nominal + worst-case). `blocked_unsafe` means the gate refused — read it as the system
   protecting the hall, not failing.
5. **Approve & deploy (expert):** deploy is shadow-mode — 45 commands recorded to the run artifact; the
   realised week is measured and fed to calibration automatically.
6. **Learn:** History tab — predicted-vs-realised trend; calibration card (n_weeks, bias, σ). Savings grow
   as confidence accumulates; never faster.
7. **If something hangs or misbehaves:** cancel from the UI; `driver.sh status / unstick <id>` for wedged
   runs; restarting the backend marks orphans failed (never silently lost).

---

## 6. Mini-glossary

**Digital twin** — a physics simulation mirroring the real plant. **EnergyPlus** — the industry building-
physics engine. **SAT / CHWST** — supply-air / chilled-water-supply temperature setpoints. **Inlet cap** —
the hard 26 °C limit at every server inlet. **Beam search** — keep-the-best-and-refine optimization.
**Robust gate** — re-testing finalists under pessimistic plant/weather scenarios; only provably-safe plans
pass. **Shadow mode** — recommend and record commands without actuating. **Calibration** — learning bias and
uncertainty from each deployed week. **σ_post** — the evidence-blended uncertainty that sizes the safety
ensemble. **PUE** — total power ÷ IT power.

---

*Evidence base: this session's merged stages 4–6 (commits `df4c6ce4`…`b044514a`), the live run database
(6 deployed weeks), calibration history (n=7), real-EnergyPlus validation sweeps, and the verified UI
screenshots. 422 backend + 104 frontend tests green at time of writing.*
