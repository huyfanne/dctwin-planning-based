# Digital Twin Dual-Loop Control Framework — Design Spec

- **Date:** 2026-06-04
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Spec home:** `dctwin/docs/superpowers/specs/`

---

## 1. Context & problem statement

A planning-based AI optimization framework for data-center operation, realizing the **Digital Twin Dual-Loop Control Framework** (see `optimization-plan.jpg`):

- **Inner loop (planning):** a Planner uses a **heuristic search** to generate candidate control sequences; a **Digital Twin Model** (EnergyPlus + a forecaster) predicts outcomes and **filters unsafe actions**; candidates are scored on objectives (minimize energy, temperature control, operational constraints).
- **Outer loop (operations):** the best plan passes **Pre-validation** + **Expert Supervision**, then **authorized commands** deploy to the physical **Data Center System**, whose **System Data** feeds back.

This framework is the successor to **OptimizationMPC** (`/mnt/lv/home/hoanghuy/mycode/dcbrain`), which used MPC + a grey-box surrogate + a 10-minute receding-horizon schedule. This design **replaces** all three of those choices and **reuses** the data-center model, the three control actions, and the objective/constraint formulation.

### What changes vs. OptimizationMPC

| OptimizationMPC (predecessor) | This framework |
|---|---|
| MPC (CMA-ES / iCEM / random shooting) | **Best-first / beam heuristic search** |
| Grey-box RC surrogate stands in for EnergyPlus | **EnergyPlus 9.5 directly** (dctwin, no surrogate) |
| 10-min receding-horizon, day-ahead + real-time | **One constant weekly setpoint**, operator re-plans weekly |
| `pyenergyplus` in-process (newer EnergyPlus) | **dctwin BCVTB / Docker**, EnergyPlus **9.5** |

## 2. Goals / non-goals

**Goals**
- Conform to the dcwiz policy-template standard (RecommendTemplate / TrajectoryPolicyTemplate, hooks, configs, the four entry modes).
- Drive EnergyPlus 9.5 directly through dctwin to score candidate weekly setpoints — no surrogate.
- Optimize **3 global weekly setpoints** (CRAH supply-air temp, CRAH airflow, CHWST) with a heuristic search bounded to ~hundreds of parallel full-week runs.
- Provide the dctwin↔dcbrain communication protocol (requirement #2) via a clean `Evaluator` seam and a versioned `recommendation.json` contract.
- Produce a pre-validation report + expert-approval gate before "deployment."
- Provide a **web app (FastAPI + React)** as the primary operator/expert interface: trigger weekly plans with live progress, review recommendations/KPIs/plots, edit setpoints, and run the approve/reject/deploy gate.

**Non-goals (v1)**
- No MPC, no grey-box surrogate, no real-time sub-hourly control.
- No real BMS deployment (sim-only; the BMS adapter is a documented stub).
- No ML forecaster (statistical only); no NN policy training.
- No time-varying intra-week schedule (one constant setpoint trio; the output schema leaves room to generalize later).

## 3. Locked decisions

| Dimension | Choice |
|---|---|
| Decision variables | **3 global weekly setpoints**, constant for the week → broadcast to 45 actuators |
| Planner | **Best-first / beam search**, coarse-to-fine over the 3-D setpoint cube |
| Twin | **EnergyPlus 9.5** via dctwin BCVTB/Docker — the calibrated **GDS tropical DC** model |
| Compute | **Hundreds of parallel full-week E+ runs** per weekly plan |
| Ground truth | **Simulation-only** (EnergyPlus is both twin and plant) |
| Forecaster | **Simple statistical** (persistence default; seasonal-naive / last-N-week optional) |
| Safety | **Hard reject + soft penalty** on ITE inlet ≤ 26 °C |
| Success metric | **Energy / PUE reduction vs current operation, 0 inlet violations** |
| Project location | `/mnt/lv/home/hoanghuy/newcode/dctwin/src/` |
| Planner placement | In-project `planner/` package, designed to be upstreamable to dcbrain |
| Integration topology | **A — in-process parallel env-pool oracle** wrapped in the dcwiz template |
| User interface | **Full web app: FastAPI backend + React (Vite/TS) frontend** |
| Job model | **Background worker + job store** (planning runs async with live progress) |
| Persistence | **Per-plan files in `runs/<id>/` + a SQLite index** for history |
| Auth | **Token-based, two roles** (operator: create/plan; expert: approve/deploy) |

## 4. The control problem

### 4.1 Model

The **GDS tropical data-center** model — a calibrated dctwin project (source: `/mnt/lv/home/hoanghuy/mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup/`). EnergyPlus **9.5**, Singapore IWEC weather, 15-min timesteps (4/hour). Topology: 22 ACUs (data hall 1F 2A) with variable-volume fans + cooling coils, a chilled-water loop with 5 supply branches + chiller + cooling tower + pumps, `ElectricEquipment:ITE:AirCooled` IT load, EMS-computed PUE. Calibrated against historical operation (`his_data_processed.csv`, `visualizer_his_vs_sim.ipynb`).

### 4.2 Control variables (3 globals → 45 actuators)

| Control | Actuator(s) in `dt.prototxt` | Physical range |
|---|---|---|
| **CRAH supply-air temp** | 22 × `data_hall_1f_2a_acu_{1..22}_supply_air_temperature_setpoint` (Schedule_Value, ACU-masked) | **20.0 – 26.0 °C** |
| **CRAH airflow** | 22 × `data_hall_1f_2a_acu_{1..22}_supply_air_mass_flow_rate` (Fan_Air_Mass_Flow_Rate) | **4.8 – 13.8 kg/s** per ACU |
| **CHWST** | 1 × `chilled_water_loop_supply_temperature_setpoint` (Schedule_Value) | **13.0 – 19.0 °C** |

All 45 are `control_type: AGENT_CONTROLLED`, each normalized `[-1,1]` via proto `normalize_config { method: LINEAR, lb, ub }`. `env.step()` expects the 45-vector of normalized values in declaration order.

### 4.3 Objective, constraints, KPIs (from `hooks.py`)

- **Objective:** minimize weekly HVAC electricity (≡ drive PUE → ~1.2).
- **Hard constraint (safety filter):** ITE inlet dry-bulb ≤ **26 °C** for every active ITE at every step.
- **Soft margins:** inlet margin below 26 °C; inlet RH within **30–60 %**; zone air ≈ **32 ± 1 °C** (tropical high-temp operation).
- **KPIs:** weekly HVAC energy (kWh), mean PUE, peak inlet temp, inlet-violation step count, % energy reduction vs baseline, % time-in-band.
- **Baseline:** current/default operating setpoints (or `his_data` historical operation).

## 5. Architecture

```
                      OUTER LOOP (weekly, human-in-loop)
   ┌─────────────────────────────────────────────────────────────────┐
   │                                                                   │
   ▼                                                                   │
 Plant (EnergyPlus, sim-only)         INNER LOOP (planning)            │
   │ System Data (energy, temps)    ┌───────────────────────────┐     │
   └──► Forecaster ──► week-ahead    │  BeamPlanner (best-first) │     │
        IT-load + weather   ───────► │   propose 3 setpoints     │     │
                                     │        │            ▲     │     │
                                     │        ▼            │KPIs │     │
                                     │   BroadcastPolicy (3→45)  │     │
                                     │        │                  │     │
                                     │        ▼                  │     │
                                     │   ParallelEnvOracle ──► N dctwin│
                                     │   full-week E+ runs (Docker)    │
                                     │        │                  │     │
                                     │        ▼ safety filter     │     │
                                     │   best feasible setpoints ─┘     │
                                     └────────┬──────────────────┘     │
                                              ▼                         │
                                     recommendation.json               │
                                              ▼                         │
                              pre-validation replay (trajectory+KPIs)   │
                                              ▼                         │
                                     Expert approval gate ──────────────┘
                                              ▼ (approved)
                                          "deploy"
```

## 6. Project layout

```
dctwin/src/                          # new self-contained template project
├── configs/
│   ├── dt/dt.prototxt               # reuse GDS env config (45 actuators, EP9.5, SGP epw)
│   │   device_key_map.json, room2ite_map.json, device_his_map.json
│   └── policy/
│       ├── plan.prototxt            # NEW: planner config (search bounds, budget, weights)
│       └── test.prototxt            # trajectory-replay config
├── models/idf/building.idf          # reuse calibrated GDS model (EP 9.5)
├── data/
│   ├── weather/SGP_Singapore.486980_IWEC.epw
│   ├── schedule/{acus,branches,pumps,workloads}/...   # forecaster regenerates workloads
│   └── his_data_processed.csv       # forecaster fit + baseline source
├── planner/                         # NEW (upstreamable to dcbrain)
│   ├── beam_search.py               #   best-first coarse-to-fine search over 3-D cube
│   ├── oracle.py                    #   Evaluator protocol + ParallelEnvOracle (dctwin seam)
│   ├── broadcast.py                 #   BroadcastPolicy: 3 globals → 45-dim action vector
│   ├── objective.py                 #   weekly scoring + hard/soft safety filter
│   └── forecaster.py                #   statistical IT-load + weather forecaster
├── hooks.py                         # reuse GDS reward/obs hooks (objective source of truth)
├── plan_weekly.py                   # NEW main entrypoint: RecommendTemplate subclass → recommendation.json
├── fit_forecaster.py                # NEW: "ai policy train" analog — fit + persist the forecaster
├── ai_trajectory_test.py            # pre-validation replay of the recommended setpoints
├── baseline_policy_test.py          # reuse: current-operation baseline for comparison
├── prevalidation.py                 # NEW: KPI report + expert-approval gate
└── deploy.py                        # NEW: sim-only deployment closing the outer loop
```

## 7. Component specifications

### 7.1 `BroadcastPolicy` (3 → 45), `broadcast.py`

A planner candidate is a 3-vector `(sat, flow, chwst)` in **physical units**. `expand()` maps it to the env's 45-dim normalized action vector in declaration order: `sat → 22 SAT setpoints`, `flow → 22 fan flows`, `chwst → 1 CHW setpoint`, each normalized via the proto `LINEAR(lb,ub)`. ACU-off masking is handled by the env. This is the only place the 3↔45 reduction lives.

### 7.2 `Evaluator` / `ParallelEnvOracle` — the dctwin↔dcbrain protocol, `oracle.py`

```python
class Evaluator(Protocol):
    def evaluate(self, candidates: list[Setpoints], forecast: Forecast) -> list[WeeklyKPI]: ...

@dataclass
class WeeklyKPI:
    total_hvac_energy_kwh: float
    pue_mean: float
    inlet_temp_max: float          # °C, across all active ITE × 672 steps
    inlet_violation_steps: int     # steps over 26 °C
    rh_violation_steps: int
    feasible: bool

class ParallelEnvOracle(Evaluator):
    # fans out n_workers dctwin EnergyPlus envs (Docker); each candidate:
    #   env.reset(); loop env.step(BroadcastPolicy.expand(cand)) for the full week;
    #   aggregate Electricity:HVAC energy + inlet temps → WeeklyKPI
```

The planner depends only on `evaluate(candidates, forecast) → KPIs`, never on EnergyPlus directly. The interface is swappable: a `MockEvaluator` for tests, a future job-queue oracle for distribution.

### 7.3 `BeamPlanner` — best-first, coarse-to-fine, `beam_search.py`

Every node is a complete, fully-evaluable 3-setpoint candidate, so the search heuristic is simply the realized objective score (no partial-state estimation).

```
search space:  sat ∈ [20,26]°C   flow ∈ [4.8,13.8]kg/s   chwst ∈ [13,19]°C

Level 0 (coarse):  g³ grid (default g=5 → 125 candidates), evaluate ALL in parallel,
                   drop infeasible (hard filter), keep top-B by score  (beam B=5)
Level ℓ=1..L:      for each beam node, sample a local neighborhood at half the previous
                   step per dim (default 6–8 neighbors), evaluate, merge, keep top-B;
                   stop early if best-score Δ < ε  OR  eval budget hit
return: best feasible candidate over all levels
```

Default budget ≈ 125 + 3·5·8 ≈ **245 full-week runs**. `g`, `B`, `L`, neighborhood size, `max_evals` are `plan.prototxt` knobs. Every level is embarrassingly parallel.

### 7.4 Objective + safety filter, `objective.py`

```
HARD safety filter (reject → score = +∞, never enters beam):
    inlet_violation_steps > tol_steps           # inlet ≤ 26 °C
    (optional) rh outside [30,60]% beyond tol

SOFT score for feasible candidates (minimize):
    cost =        E_hvac_kwh                     # weekly Electricity:HVAC (≡ PUE↓)  — dominant
           + λ_T · Σ_t max(inlet_t − 25, 0)      # margin below the 26 °C cap
           + λ_H · Σ_t humidity_excursion
           + λ_Z · Σ_t |zone_t − 32|_band
```

`E_hvac_kwh` dominates; λ-terms are small configurable margins/tie-breakers. Scoring from EnergyPlus itself structurally avoids the predecessor's surrogate-exploitation failure mode.

### 7.5 Forecaster, `forecaster.py` + `fit_forecaster.py`

```python
class Forecaster(Protocol):
    def forecast(self, week_start: date) -> Forecast: ...

@dataclass
class Forecast:
    workload_schedules: dict[str, list[float]]   # per-ITE CPU-loading → data/schedule/workloads/*.json
    weather_window: WeatherSpec                  # epw slice / run-period for the week
```

- **IT workload** — fit on `his_data_processed.csv`. v1 default **persistence**; seasonal-naive / last-N-week-average configurable.
- **Weather** — v1 default: TMY EPW window for the planning calendar week; optional persistence adjustment via external inputs.
- The `Forecast` is consumed by the Oracle, which writes the workload JSONs and sets `simulation_time_config` to the planning week. Weeks crossing Dec 31→Jan 1 use the template's `configure_run_period` year-split; v1 evaluation weeks avoid the wrap.

## 8. Template integration & output contract

### 8.1 The four template modes

| Template mode | This framework | Base class | Output |
|---|---|---|---|
| ai policy test | `plan_weekly.py` — Monday planning run | `RecommendTemplate` → `WeeklyPlanTemplate` | `recommendation.json` |
| ai policy train | `fit_forecaster.py` — fit + persist forecaster (only trainable component) | plain `main()` | `forecaster.pkl` |
| ai trajectory test | `ai_trajectory_test.py` — replay recommended setpoints | `TrajectoryPolicyTemplate(policy="ai")` | `temperature_data_ai.csv` |
| baseline trajectory test | `baseline_policy_test.py` — current-operation setpoints (reuse) | `TrajectoryPolicyTemplate(policy="baseline")` | `temperature_data_baseline.csv` |

`hooks.py`, `configs/`, `models/`, and `planner/` (the "policy" slot) complete the conforming layout.

### 8.2 `recommendation.json` — inner→outer loop contract (versioned)

```json
{
  "schema_version": "1.0",
  "plan_id": "gds-2013-W46",
  "week_start": "2013-11-11", "week_end": "2013-11-17", "cadence": "weekly",
  "setpoints": {
    "crah_supply_air_temperature_c": 24.0,
    "crah_supply_air_mass_flow_rate_kg_s": 6.2,
    "chilled_water_supply_temperature_c": 18.0
  },
  "predicted_kpis": {
    "total_hvac_energy_kwh": 0.0, "pue_mean": 0.0,
    "inlet_temp_max_c": 0.0, "inlet_violation_steps": 0,
    "energy_reduction_vs_baseline_pct": 0.0
  },
  "forecast": {"method": "persistence", "weather": "TMY-window"},
  "search":   {"evals": 245, "beam_width": 5, "levels": 3},
  "status": "pending_approval"
}
```

`status`: `pending_approval → approved → deployed`. Constant for the week; structure leaves room for a time-indexed schedule later without breaking consumers.

## 9. Outer loop — pre-validation, expert supervision, deployment

- **`prevalidation.py`** consumes `recommendation.json`, triggers the trajectory replay, computes a KPI report (energy, PUE, peak inlet, % time-in-band, violations, **% energy reduction vs baseline**) + predicted-vs-baseline plots (in the `visualizer_his_vs_sim` style). The diagram's **Pre-validation** box.
- **Expert supervision** = human gate: review the report; approve / reject / edit. The **web app (§14) is the primary interface** for this; a CLI action (`--approve`) and direct `status` editing remain as the underlying mechanism. No silent auto-deploy.
- **Deployment (sim-only)**: on approval, `deploy.py` runs the **plant** (EnergyPlus) for the week with approved setpoints, logs realized KPIs; realized System Data feeds the next week's forecaster — closing the loop. Because twin = plant in v1, predicted ≈ realized; the roles stay separate so a future **perturbed-plant** mode or **real BMS adapter** slots into the same `deploy()` contract. BMS adapter is a documented stub in v1.

> **Erratum (2026-06-07, LATER sub-project A):** in sim-only v1 the realized load equals the injected
> forecast, so the realized-feedback path is the **calibration** loop (output-residual bias/σ → corrected
> objective), not the forecaster. `refit_from_history` is a documented no-op seam that activates only with
> real per-step telemetry. See `2026-06-07-close-prove-learning-loop-design.md` §4.2.

## 10. EnergyPlus & framework data formats (requirement #8)

| Format | Role |
|---|---|
| **`.idf`** (EP 9.5 Input Data File) | The physical model — zones, HVAC (22 ACUs/fans, chiller, cooling tower, CHW + condenser loops, pumps), `ElectricEquipment:ITE:AirCooled`, schedules, output variables. Single source of truth (`models/idf/building.idf`). dctwin injects BCVTB/ExternalInterface actuators at runtime via `opyplus`. |
| **`.epw`** (EnergyPlus Weather) | Hourly TMY weather (dry-bulb, RH, wind, solar…) for Singapore; passed to EnergyPlus `-w`. The forecaster's weather window slices this. |
| **`.idd`** (Input Data Dictionary) | EnergyPlus object schema; used by eppy/opyplus to parse/validate the IDF. Bundled with EP 9.5. |
| **`building.json`** (dclib Building) | High-level DC description that generated the IDF via `IDFBuilder`. Authoring source, not an EP runtime format. |
| **`device_key_map / room2ite_map / device_his_map .json`** | dctwin maps: model object names ↔ logical device keys ↔ historical-data columns (obs/reward + calibration). |
| **`data/schedule/**/*.json`** | dctwin PRE_SCHEDULED inputs: plain JSON float arrays (per-step) for IT workload (CPU loading), ACU/branch on-off, pump flow. Forecaster regenerates the workload set. |
| **`dt.prototxt`** (protobuf text) | `DTEngineConfig`: `model_file`, `weather_file`, `simulation_time_config`, the 101 actions, observations. The env contract. |
| **`his_data_processed.csv`** | Historical measured data (PDU powers, PUE, ACLF/WCLF, temps) for forecaster fit + baseline. |
| **`recommendation.json`** | Planner output contract (§8.2). |
| **`temperature_data_*.csv`** | Trajectory outputs (per-step temps/power). |
| **EP run outputs** (`.eso .err .html .rdd .mdd .eio .end`) | Generated per run in `LOG_DIR`; dctwin reads observations live over the BCVTB socket, not post-hoc from `.eso`. |
| **epJSON** | *Not used* — dctwin accepts IDF only (noted for completeness). |

## 11. Error handling

- **Per-candidate E+/Docker failure** (crash, BCVTB timeout, EP severe error): Oracle catches it, marks candidate `feasible=False` / `score=+∞`, logs, continues. Retry once for transient issues, then drop. One bad run never aborts the search.
- **Run timeout**: per-run wall-clock cap; on timeout kill the container and mark failed.
- **All candidates infeasible**: fall back to the safest candidate (min violation count: coolest SAT/CHW + max flow), set `status: infeasible_fallback` for expert attention. Never return nothing.
- **Resource bounds & cleanup**: cap `n_workers` to host capacity, queue the rest; guarantee Docker container + temp-dir teardown even on exception.
- **Forecaster / missing history**: insufficient `his_data` → fall back to a typical profile and warn.
- **Fail-fast validation at startup** (before any sim): bounds ordered, budget > 0, weights ≥ 0; broadcast dim == 45; reject Dec 31→Jan 1 year-wrap weeks in v1.
- **Provenance**: log forecast + seed + search params + per-candidate KPIs so every plan is reproducible and auditable.

## 12. Testing strategy

- **Unit (fast, no E+):** `broadcast` (3→45 order, LINEAR round-trip, masking); `objective` (hard-reject on violation, soft cost monotonic in energy, infeasible→+∞); `beam_search` against a **MockEvaluator** with a known analytic cost surface (converges near optimum, honors beam/levels/early-stop/budget); `forecaster` (shapes from fixture his_data, weather-window slicing); `oracle` KPI aggregation from a synthetic obs stream.
- **Integration (slow, marked optional):** one short run (1–2 day window, 1 worker) through the real `ParallelEnvOracle` (env launch, BCVTB handshake, broadcast applied, KPIs returned, container cleaned up); a tiny end-to-end plan (g=2 → 8 candidates, 1 refine level) producing a sane `recommendation.json`.
- **Acceptance (manual/nightly):** full weekly plan on a representative week → pre-validation + baseline → assert **0 inlet violations** and **energy reduction vs baseline > 0**.
- **Regression:** snapshot recommendation KPIs for a fixed seed/week to catch drift.

The **MockEvaluator** (drop-in `Evaluator`) lets the entire planner be TDD'd without EnergyPlus cost.

## 13. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **M0** | Scaffold `src/` from the GDS layout; reuse model/configs/hooks/weather; run `baseline_policy_test.py` on a short window | dctwin / Docker / EP 9.5 stack works end-to-end |
| **M1** | `broadcast.py` (3→45) + `ParallelEnvOracle.evaluate()` for one candidate over a short window → `WeeklyKPI` | the expensive twin seam, de-risked early |
| **M2** | `objective.py` — hard reject + soft cost; wire into Oracle | scoring + safety filter |
| **M3** | `BeamPlanner` against MockEvaluator (TDD), then real Oracle on a short window | search logic (fast, no E+) |
| **M4** | `fit_forecaster.py` + `forecaster.py` (persistence) → regenerate workload schedules | week-ahead inputs |
| **M5** | `plan_weekly.py` (`WeeklyPlanTemplate`) → full-week plan → `recommendation.json` | the Monday entrypoint |
| **M6** | `ai_trajectory_test.py` replay + `prevalidation.py` report/plots + approval gate + `deploy.py` (sim-only) | the outer loop |
| **M7** | Full weekly run on a representative week | acceptance: 0 violations + energy reduction |
| **M8** | Web app (Plan 4): FastAPI backend (jobs/store/auth) + React frontend | operator/expert use the framework via the browser |

M0–M2 attack the costly EnergyPlus seam first; M3 is pure logic. M8 (the web app) layers on top of the working core (M0–M7). Each milestone is a review checkpoint.

## 14. Web application (FastAPI + React)

The primary operator/expert interface. It wraps the framework (Plans 1–3) as a service — no control logic is reimplemented. Built in Plan 4.

### 14.1 Architecture

```
React (Vite + TypeScript)  ──JSON/WebSocket──►  FastAPI  ──►  WeeklyPlanTemplate → BeamPlanner → ParallelEnvOracle
  Dashboard / New Plan /                          │              (the existing Python framework)
  Review & Approve / History                      ▼
                                        background worker + job store
                                        runs/<plan_id>/{recommendation.json,
                                          progress.json, trajectory_*.csv, report.md}
                                        + SQLite index (history/list)
```

- **Backend:** FastAPI. Planning is long-running (hundreds of full-week E+ runs), so `POST /api/plans` enqueues a **background-worker job**; the worker runs `WeeklyPlanTemplate` and streams progress (a `BeamPlanner` progress callback → `progress.json` → `WS /api/plans/{id}/progress`). The oracle's process pool runs underneath the worker.
- **Persistence:** per-plan artifacts in `runs/<plan_id>/`; a **SQLite index** (`runs/index.db`) backs history/list views. No DB server.
- **Auth:** **token-based, two roles** — `operator` (create/trigger plans) and `expert` (approve/reject/deploy). Approval/deploy endpoints require the `expert` role.

### 14.2 API surface (FastAPI)

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /api/plans` | operator | start a weekly plan (week_start, search params) → `plan_id`, async job |
| `GET /api/plans` | any | history list (from SQLite index) |
| `GET /api/plans/{id}` | any | `recommendation.json` + status + KPIs |
| `WS /api/plans/{id}/progress` | any | live evals/total + current-best stream |
| `GET /api/plans/{id}/trajectory` | any | per-step series (ai + baseline) for plots |
| `GET /api/topology` | any | schematic 1F-2A hall layout (CRAHs, rack rows/aisles, plant) for the 3D view |
| `PATCH /api/plans/{id}/setpoints` | expert | edit setpoints before approval |
| `POST /api/plans/{id}/approve` \| `/reject` | expert | the supervision gate |
| `POST /api/plans/{id}/deploy` | expert | sim-only deploy → realized KPIs |

### 14.3 Frontend (React + Vite + TS)

Five views, built with the frontend-design skill: **Dashboard** (latest plan: setpoints, KPIs, status badge), **New Plan** (params + live progress: progress bar, evals, best-score-per-level chart), **Review & Approve** (plan-vs-baseline KPI table + per-step inlet/power/PUE plots, setpoint editor, approve/reject), **History** (past plans, predicted-vs-realized energy trend), and **Digital Twin (3D)** (§14.5). Charting via Recharts; 3D via three + @react-three/fiber + @react-three/drei.

### 14.4 Layout additions

```
src/
├── webapp/                # FastAPI backend (Plan 4)
│   ├── main.py            #   app + routes
│   ├── jobs.py            #   background worker + job store
│   ├── store.py           #   runs/<id>/ + SQLite index access
│   ├── auth.py            #   token auth + operator/expert roles
│   ├── schemas.py         #   pydantic request/response models
│   └── topology.py        #   schematic 1F-2A hall layout from building.json (3D view)
└── frontend/              # React app: src/pages/{Dashboard,NewPlan,Review,History,DigitalTwin3D}
                           #   + src/three/{HallScene,Airflow,CRAH,RackRows,Plant}.tsx
```

### 14.5 Digital Twin (3D) view

A detailed, interactive **schematic 3D** of the **controlled 1F 2A hall** (the model has no real geometry — 0 detailed surfaces, zones at origin — so the layout is generated from the logical topology). Backend `webapp/topology.py::build_hall_topology(building_json, dt_prototxt, hall="1f 2a")` produces a deterministic schematic: hall box, **22 CRAH units** along the perimeter, **server-rack rows** in **cold/hot-aisle** pairs, and a **plant block** (chiller/cooling tower/pumps) with CHW pipe links; served at `GET /api/topology`.

Frontend (`react-three-fiber` + `drei`): renders the hall shell, CRAH boxes, instanced racks, and plant/pipes with **OrbitControls** + click-to-inspect, plus a **HUD** of the selected plan's 3 setpoints + KPIs. **Rack coloring** is a thermal gradient anchored on the plan (**SAT → max inlet**, cold-aisle blue → hot-aisle red). **Airflow animation**: a particle system flowing **CRAH → cold aisle → racks → hot aisle → return**, with **particle speed ∝ the CRAH airflow setpoint** and **color ∝ SAT→inlet** (driven by `useFrame`), so changing the recommended airflow visibly changes the flow. Data: `GET /api/topology` (static) + `GET /api/plans/{id}` (setpoints/KPIs). v1 uses the schematic SAT→inlet_max gradient for racks; real per-rack inlet temps from a trajectory run are a noted follow-up.

## 15. Open questions / future work

- **Perturbed-plant mode** for twin≠plant realism (model mismatch), reusing the `deploy()` contract.
- **ML forecaster** behind the same `Forecaster` interface.
- **Time-indexed weekly schedule** (day/night blocks) once the constant-setpoint v1 is validated — the `recommendation.json` schema already allows it.
- **Upstream `planner/` into dcbrain** as a first-class planner once stable.
- **Real BMS deployment adapter** behind the documented `deploy()` stub.

## 16. Reference file index

- **Templates (framework):** `/mnt/lv/home/hoanghuy/newcode/dcwiz-ai-engine-deploy-master/dcwiz_policy_template/dcwiz_policy_template/{recommend_template.py, trajectory_policy_template.py}`
- **Sample template (layout to mirror):** `…/dcwiz_policy_template/examples/sample_template/{hooks.py, ai_policy_test.py, ai_trajectory_test.py, baseline_policy_test.py, ai_policy_train.py, configs/, data/, models/, policy/}`
- **dctwin (twin):** `/mnt/lv/home/hoanghuy/newcode/dctwin/dctwin/{registration.py, gym_envs/, third_parties/eplus/{core.py,parser.py}, utils/protos/dt_engine.proto}`
- **dcbrain v1.0.2 (planner host):** `/mnt/lv/home/hoanghuy/newcode/dcbrain/dcbrain/{policies/model_based/mpc_policy.py, utils/{config.py,registration.py}, safety_layer/}`
- **OptimizationMPC (REPLACE source / control-problem reference):** `/mnt/lv/home/hoanghuy/mycode/dcbrain/{scripts/run_7day_planner.py, dcbrain/models/graybox_largedc.py, dcbrain/envs/energyplus/, docs/get_started/large_dc_case_study.md}`
- **GDS tropical DC model (the actual model + working template project to fork):** `/mnt/lv/home/hoanghuy/mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup/{configs/dt/dt.prototxt, models/idf/building.idf, hooks.py, data/}`
- **Workflow diagram:** `/mnt/lv/home/hoanghuy/newcode/optimization-plan.jpg`
- **Control-problem slides:** `/mnt/lv/home/hoanghuy/newcode/largedc_mpc_two_slide_report_v2.pptx`
