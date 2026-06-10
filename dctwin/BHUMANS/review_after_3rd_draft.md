# Review After the 3rd Draft — Digital Twin Dual‑Loop Control Framework

**Date:** 2026‑06‑09
**Reviewed against:** the original plan diagram (`optimization-plan.jpg`)
**Audience:** written to be understandable without a background in data centers or software.

---

## 0. The one‑paragraph summary (for anyone)

We set out to build a **"digital twin"** of a data‑center cooling system — a high‑fidelity computer
simulation of the real building — and wrap it in a tool that **recommends, once a week, the best
cooling settings** to save energy **without ever letting the servers get too hot**. After three
drafts, the **"thinking" half of the system is built and works well**: it forecasts next week's
conditions, simulates hundreds of "what‑if" cooling settings in a real physics engine (EnergyPlus),
and searches for the cheapest safe option, with multiple safety nets. A polished **web app** lets a
person create plans, watch the search live, review the recommendation (including a 3‑D view of the
hall), and approve/deploy it. **The main thing still missing is the connection to a real data
center**: today the system "deploys" to *another simulation*, not to real cooling equipment, and the
web app shows *plan results*, not a *live feed* of the real building. So as of the 3rd draft this is a
**very capable recommendation‑and‑review engine running entirely in simulation**, not yet a
closed‑loop controller of a physical site. The rest of this document explains exactly what is and
isn't done, why, the known accuracy caveats, and a concrete roadmap to finish it.

---

## 1. What the original plan asked for (the diagram, in plain words)

The plan describes a **dual‑loop control framework** — two nested feedback loops:

- **Inner loop ("planning"):** A **Digital Twin Model** (a *Forecaster* for IT workload + weather,
  feeding a *physics simulation* in EnergyPlus that predicts temperatures, humidity, energy use and
  equipment status) is driven by a **Planner** (a *heuristic search* that tries many candidate
  cooling settings and scores them against three goals: **minimise energy**, **keep temperature in
  control**, and **respect operational/safety constraints**). Unsafe options are filtered out.

- **Outer loop ("deployment"):** The best plan goes through **Pre‑validation** (a safety
  double‑check), then **Expert Supervision** (a human does real‑time monitoring, strategy evaluation,
  override intervention, and strategy deployment), and finally **authorised control commands are sent
  to the real Data Center System**. The real system's new **System Data** (sensor readings) flows back
  to the forecaster, closing the loop.

The sections below grade each box.

---

## 2. Scorecard: plan vs. 3rd draft

Legend: ✅ built & working · 🟡 partly built / simulation‑only · ❌ not built yet

| Plan element | Status | One‑line verdict |
|---|---|---|
| **Forecaster** (IT load) | ✅ | Persistence + seasonal (weekday × time‑of‑day) + new calendar‑level alignment. Solid, tested. |
| **Forecaster** (weather) | 🟡 | Uses a **fixed historical weather file** for the chosen week; it does **not forecast** future weather. |
| **Digital Twin Model** (EnergyPlus physics) | ✅ | Real EnergyPlus 9.5 in Docker is the in‑the‑loop oracle; predicts inlet temps, zone temps, humidity, power. |
| **Planner** (heuristic search) | ✅ | Coarse‑to‑fine beam search over 3 setpoints → 45 actuators. Well‑tested. |
| **Objectives** (energy / temperature / constraints) | ✅ | Energy + soft temperature/humidity penalties + **hard inlet ≤ 26 °C** cap. |
| **Unsafe‑action filtering** | ✅ | Hard feasibility gate + a "robust" worst‑case re‑check + a deploy backstop. |
| **Pre‑validation** | ✅ | Re‑runs the recommendation on the nominal **and** a worst‑case degraded plant; emits trajectories. |
| **Expert Supervision — evaluation & override** | ✅ | Approve / reject / **edit setpoints** / deploy, with operator vs. expert roles. |
| **Expert Supervision — real‑time monitoring** | 🟡 | The app shows **plan predictions & post‑run results**, not a **live feed** of the real building. |
| **Strategy deployment to the real DC** | ❌ | **Simulation‑only.** Deploy runs a *perturbed EnergyPlus plant*; the real‑equipment connector is a documented stub. |
| **System Data feedback / calibration** | 🟡 | Auto‑calibration after each deploy works — but it learns from **simulated** outcomes, not real sensors. |
| **Web app visualization** | ✅ | 6 pages incl. live search progress, KPI review, history trends, and a 3‑D hall view. |

**Bottom line:** the **inner loop is essentially complete and high‑quality**; the **outer loop is
structurally complete but closed onto a simulator, not a real site.**

---

## 3. What IS implemented (in plain language, with the engineering detail underneath)

### 3.1 The Forecaster — "what will next week look like?"
- **IT workload:** three methods — *persistence* (next week ≈ last week), *seasonal* (learns the
  typical shape for each weekday and time of day), and a **new calendar‑level adjustment** (added this
  draft) so a week planned in December reflects December's load level, not just the weekday pattern.
- **Reality check we did:** the real IT load in this hall is **very flat** — it varies only **~1.3%
  from month to month** — so weather, not load, drives week‑to‑week differences. That's a property of
  the data, not a bug.
- **Weather:** the chosen week pulls the matching slice from a **real historical weather file**
  (EnergyPlus EPW), with a guard that refuses weeks outside the file's coverage. It does **not**
  predict future weather.

### 3.2 The Digital Twin Model — "a physics simulation of the hall"
- The simulation is **EnergyPlus 9.5**, the industry‑standard building‑energy engine, run inside
  Docker and coupled live (via BCVTB sockets) so the planner can drive it step by step.
- Each simulated week reports: **per‑rack inlet air temperatures** (the safety‑critical signal),
  zone temperatures, **humidity**, and **power** (split into IT vs. cooling).
- The planner controls **3 global "knobs,"** automatically broadcast to **45 individual actuators**
  in the controlled 1F‑2A hall:
  1. **CRAH supply‑air temperature (SAT)** — how cold the cooling units blow air (20–26 °C),
  2. **CRAH airflow** — how hard they blow (4.8–13.8 kg/s),
  3. **Chilled‑water supply temperature (CHWST)** — how cold the chilled water is (13–19 °C).

### 3.3 The Planner — "search for the cheapest safe settings"
- **Coarse‑to‑fine beam search:** it lays a coarse grid over the three knobs, simulates each, keeps
  the best few, then zooms in around them — repeating a few times. Every candidate is a **full‑week
  EnergyPlus run**, parallelised across CPU processes.
- **The score it minimises:** energy use **+** small penalties for nudging temperature/humidity out
  of comfort bands. **Any setting that lets a rack inlet exceed 26 °C is rejected outright** (a hard
  constraint, not a penalty).
- **Day/night scheduling (optional):** it can also recommend *different settings for day vs. night*
  (a warm‑started local search), not just one constant setting.

### 3.4 Safety — "three nets, not one"
1. **Hard cap:** reject any week with a single 15‑minute step over 26 °C inlet.
2. **Robust re‑check:** re‑simulate the finalists on **deliberately degraded "what if the plant is
   weaker than expected" scenarios**, and only keep options that stay safe in the worst case
   (picking by worst‑case safety, then by worst‑case energy).
3. **Deploy backstop:** if the (simulated) deployed week breaches the cap, it is marked
   **deploy‑blocked**, never "deployed."
- A **calibration margin** (k·σ) pre‑tightens the cap based on how uncertain the twin has been
  historically, so the search leaves headroom.

### 3.5 The outer loop — "review, approve, deploy, learn"
- **Pre‑validation** independently re‑runs the recommendation on a nominal **and** a worst‑case
  plant and saves **inlet‑temperature trajectories** (so a reviewer can see the safety margin over
  time).
- **Expert workflow** with a proper state machine: a plan goes
  `queued → running → pending‑approval → approved → deploying → deployed` (with `rejected`,
  `failed`, `infeasible‑fallback`, `blocked‑unsafe`, `deploy‑blocked`, `cancelled` branches). An
  **operator** can create/cancel/delete; an **expert** can approve/reject/**edit setpoints**/deploy.
  Crucially, a plan flagged **blocked‑unsafe cannot be force‑approved** — safety wins by default.
- **Calibration loop:** after each deploy, the system compares predicted vs. realised KPIs, learns a
  **bias correction** and an **uncertainty (σ)** per metric (with a "fading floor" so one week can't
  make it over‑confident), and feeds that back into the next plan's safety margin.

### 3.6 The web app — "the operator's cockpit"
- **Six pages:** **Login** (token, two roles), **Dashboard** (latest plan at a glance), **New Plan**
  (set the week + search settings, then watch **live progress** stream in), **Review** (full KPI
  comparison vs. an as‑operated baseline, setpoint editor, confidence bands, inlet trajectory chart,
  realised‑vs‑predicted after deploy, calibration card), **History** (sortable/filterable table +
  a predicted‑vs‑realised energy trend), and **Digital Twin 3‑D** (an interactive Three.js view of
  the hall with airflow particles and a setpoint HUD).
- **16 API endpoints**, token auth that **fails closed**, a single‑origin deployment, and a live
  **Server‑Sent‑Events** progress stream with reconnect.

### 3.7 Engineering quality
- **~287 Python unit tests + 78 frontend tests all pass**, plus **8 Docker‑gated integration tests**
  that exercise the real EnergyPlus loop end‑to‑end.
- **16 design specs + 18 implementation plans** under `docs/superpowers/`, every feature built
  **test‑first**. The recommendation artifact is **schema‑versioned 1.0 → 1.7** with backward
  compatibility.

---

## 4. What is NOT implemented — and why

| Missing capability | Status | Why it's not done (honest reason) |
|---|---|---|
| **Connection to a real data center (BMS)** | ❌ | The deploy step calls a **simulated** plant; the real‑equipment adapter is an intentional, documented **stub** (`deploy.py`). Closing it needs site access, a BMS protocol (BACnet/Modbus/API), and safety sign‑off — out of scope for a simulation‑stage draft. |
| **Live telemetry monitoring** in the app | ❌ | The app visualises **plan predictions and post‑run results**, not a real‑time sensor stream. There is no historian/MQTT/BMS feed wired in yet (depends on the BMS connection above). |
| **Weather *forecasting*** | 🟡 | Today it uses a **real but fixed** weather file for the week; it doesn't predict future weather or carry weather uncertainty into the search. |
| **Active humidity control** | 🟡 | Humidity is **measured and constrained** (penalty + optional hard limit) but not a **control knob** — there's no modelled dehumidification action. |
| **Physics re‑calibration of the twin** | 🟡 | Only **output‑bias** calibration is live. Re‑tuning EnergyPlus *parameters* from data is a **stubbed seam** — it needs real per‑step telemetry, which doesn't exist yet. |
| **Forecaster re‑fit from realised data** | 🟡 | A stub — in simulation the "realised" load equals the injected forecast, so there's nothing new to learn until real telemetry arrives. |
| **Carbon / time‑of‑use / demand‑charge awareness** | ❌ | The objective minimises **kWh only**. Tariff‑ and carbon‑aware optimisation isn't in scope yet. |
| **Demand‑side flexibility** (load shifting) | ❌ | The planner only moves **cooling** knobs; IT load is treated as fixed. |
| **Per‑equipment / per‑rack drill‑down & alerts** | ❌ | KPIs are **hall‑level**; there's no per‑ACU breakdown, anomaly alerting, or mid‑week override UI. |

**The through‑line:** every ❌ above is either (a) **blocked on having a real site to connect to**, or
(b) **a deliberate scope choice** for a simulation‑stage tool. None is a hidden defect — they're
documented seams.

---

## 5. Known issues & accuracy caveats (the "fidelity" honesty section)

These are subtle but important for the goal of **high‑fidelity recommendations**. They were found and
verified with real EnergyPlus runs during this draft.

1. **"Deployment" is simulation‑to‑simulation.** The realised KPIs the system learns from come from a
   *degraded EnergyPlus plant*, **not real equipment**. So the calibration loop is *exercised and
   correct in structure*, but its numbers are not yet grounded in reality.

2. **The recirculation parameter is currently inert.** The model has a "10% hot‑air recirculation"
   assumption, but sweeping it from 5% to 50% changed the simulated inlet temperature **not at all**
   (verified at two airflows). The inlet is driven by **supply‑air temperature + fan heat**, with
   **no recirculation penalty** — i.e. the model behaves as if containment were near‑perfect.
   **Consequence:** the inlet safety margin may be **optimistic** versus a real hall with imperfect
   hot/cold‑aisle separation. *Calibrating the 10% value is pointless until this is made "live."*

3. **The safety signal is correct, but only as accurate as the physics.** The hard cap correctly
   reads the **true per‑rack inlet temperature** (not zone average) — good. But that value is only as
   trustworthy as the (currently optimistic) recirculation model above.

4. **The energy metric is asymmetrically scoped (by design).** "Controllable HVAC energy" = the
   controlled hall's fans **+ the whole shared chiller/CHW plant**. The *changes* are correctly driven
   by the controlled hall (other halls are held fixed), but the *absolute level* includes shared
   plant, so it isn't a per‑hall‑isolated number. The savings % (same metric on both sides) is honest
   and, if anything, conservative.

5. **Week‑to‑week variation is dominated by weather, not load.** Because the IT load is flat (~1.3%
   monthly), two different weeks will look similar unless the weather differs. This is physically
   correct for this site, but it means the tool's value here is **finding the cheapest safe operating
   point**, more than *tracking load swings*.

6. **Robustness coverage is modest.** The worst‑case re‑check uses **3 scenarios** with assumed
   degradation factors — a reasonable hedge, not a calibrated uncertainty model.

---

## 6. So… how trustworthy are the recommendations today?

- **Mechanically sound and safe‑by‑construction:** the search genuinely optimises, the safety cap
  genuinely binds, and three independent nets guard against unsafe deploys. We verified end‑to‑end
  that a real plan now picks a sensible interior optimum (e.g. SAT 24.5 °C / flow 4.8 kg/s / CHWST
  19 °C, ≈ **+3.2% energy saving** vs. as‑operated, zero violations) — and that earlier "always the
  same answer" behaviour is gone.
- **But "high fidelity" is not yet *calibrated* fidelity:** the twin hasn't been validated against
  real measured inlet temperatures, and the one parameter meant to capture recirculation risk is
  currently inert. **Treat current numbers as directionally correct and safety‑conservative, not as
  field‑validated.**

---

## 7. Recommended next steps (a roadmap toward the stated goal)

Goal restated: *a physics‑based digital twin + web visualization that helps a DC operator do weekly
cooling planning to minimise energy without breaching safety, with high‑fidelity recommendations.*

### Tier A — Close the loop to reality (highest impact)
1. **Implement the BMS adapter** (`BmsAdapter.apply(setpoints, week)`): write approved setpoints to
   the real cooling system via its protocol (BACnet/Modbus/vendor API), starting **read‑only /
   shadow‑mode** (recommend but don't actuate) for trust‑building.
2. **Ingest real telemetry**: stream live inlet temps, power, humidity and equipment status from the
   BMS/historian into the store, so "realised" KPIs and calibration use **real** data.
3. **Live monitoring dashboard**: add a real‑time view (inlet heat‑map, power, PUE, **alerts when any
   rack nears 26 °C**) and **setpoint‑compliance tracking** (did the plant actually hold the commanded
   settings?). This delivers the "real‑time monitoring + override" part of Expert Supervision.

### Tier B — Raise twin fidelity (so recommendations can be trusted in the field)
4. **Fix the recirculation physics** so the parameter is *live* (inlet responds to airflow shortfall
   / containment), **then calibrate it to measured rack inlets** — this directly de‑risks the safety
   margin.
5. **Activate physics re‑calibration** (`recalibrator`) once real per‑step telemetry exists: tune
   EnergyPlus parameters (not just output bias) as weeks accumulate.
6. **Per‑rack / per‑ACU breakdown** in KPIs and the 3‑D view, so hotspots are visible.

### Tier C — Smarter planning
7. **Weather forecasting + uncertainty**: replace the fixed weather slice with a short‑horizon
   forecast and propagate weather uncertainty through the robust scenarios.
8. **Carbon‑ / tariff‑aware objective**: optionally weight energy by time‑of‑use price or grid carbon
   intensity (big operational value, small code change to the objective).
9. **Expand robustness**: more scenarios and data‑driven degradation factors once real data exists.

### Tier D — Operator experience & assurance
10. **Mid‑week override UI** (pause/adjust if conditions change) and **failure explainability** (plain
    reasons for "blocked‑unsafe"/"infeasible").
11. **End‑to‑end tests** (browser + backend), not just mocked unit tests, before any real‑site pilot.
12. **Shadow‑mode pilot**: run the system recommending‑only against a real hall for several weeks,
    compare predicted vs. truly realised, and only then enable closed‑loop actuation.

**Suggested order:** A1–A3 (connect + monitor) and B4 (recirculation fix) first — they convert this
from "a strong simulator" into "a trustworthy operator tool." Everything else builds fidelity and
polish on top.

---

## 8. Mini‑glossary (for non‑specialists)

- **Digital twin:** a computer simulation that mirrors a real system closely enough to test changes
  safely before doing them for real.
- **EnergyPlus:** the industry‑standard physics engine that simulates a building's heat, airflow and
  energy use.
- **Setpoint:** a target value an operator sets (e.g. "blow air at 23 °C"). The 3 here are supply‑air
  temperature, airflow, and chilled‑water temperature.
- **Inlet temperature:** the air temperature *entering the servers* — the safety‑critical number;
  must stay ≤ 26 °C.
- **CRAH / ACU:** the room cooling units (air handlers) that blow conditioned air to the racks.
- **CHWST:** chilled‑water supply temperature — how cold the water feeding the cooling coils is.
- **PUE:** Power Usage Effectiveness — total facility power ÷ IT power; lower is more efficient.
- **Beam search:** a search strategy that keeps the best few candidates at each step and refines
  around them, instead of trying everything.
- **Robust / worst‑case check:** re‑testing a plan under pessimistic "what if the equipment is weaker"
  assumptions, to avoid plans that are only safe on paper.
- **Calibration:** automatically nudging the twin's predictions toward reality as real outcomes come
  in.
- **BMS (Building Management System):** the real control system that actually commands the cooling
  equipment — the thing we'd connect to in Tier A.
- **Sim‑only / closed loop:** "sim‑only" means we deploy to another simulation; "closed loop" means
  commands reach real equipment and real sensors feed back.

---

*Prepared as the post‑3rd‑draft review. Evidence: source survey of `src/planner/`, `src/webapp/`,
`src/frontend/`, the spec/plan corpus under `docs/superpowers/`, the recommendation schema (1.0→1.7),
and real‑EnergyPlus validation runs performed during this draft. ~287 Python + 78 frontend unit tests
pass; 8 Docker‑gated integration tests cover the real loop.*
