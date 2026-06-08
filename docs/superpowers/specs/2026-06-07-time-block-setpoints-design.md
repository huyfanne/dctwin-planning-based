# Time-Block (Day/Night) Setpoints — Design Spec (sub-project B)

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope tier:** the first increment of LATER **sub-project B** (finer control). Per-zone / per-hall
  setpoints and >2 / configurable blocks are deferred to later increments.
- **Predecessor specs (merged):** NOW, NEXT, and LATER sub-project A.

---

## 1. Context & problem statement

The framework optimizes **3 global setpoints, constant for the whole week** (CRAH supply-air temp, CRAH
airflow, CHWST), broadcast to the 45 actuators of the controlled 1F 2A hall. The recommendation schema
already "leaves room" for a time-indexed schedule. The biggest remaining energy lever that is tractable on
the current model (single controlled hall, ultra-flat IT load) is **time-block control**: a **day/night**
schedule that exploits the Singapore tropical **diurnal weather swing** — cooler nights let the optimizer
relax cooling (warmer SAT/CHWST, lower fan flow) without breaching the 26 °C inlet cap, saving energy.

**Goal:** add an opt-in **day/night schedule** found by a **warm-started** search that reuses the existing
3-D optimizer, evaluated by the real full-week EnergyPlus sim with the action switched by time-of-day, under
the same safety gate.

## 2. Goals / non-goals

**Goals**
- A `WeeklySchedule` (day/night blocks, each a `Setpoints`) the oracle evaluates in ONE full-week sim,
  switching the env action by local time-of-day.
- A two-stage **warm-start** search: stage 1 = the existing 3-D constant search + robust gate; stage 2 =
  a local day/night refinement seeded at the robust constant winner (never worse than constant).
- Opt-in via `PlanRequest.time_block` (default off → today's behavior, no extra cost); recommendation
  schema 1.5 with a `schedule` block; a Review schedule card + a New-Plan toggle.
- The hard inlet ≤ 26 °C, the k·σ margin, calibration correction, and the deploy backstop all still apply.

**Non-goals (deferred)**
- Per-zone / per-hall setpoints (sub-project B later increments; GDS model changes for per-hall).
- More than 2 blocks / configurable boundaries (fixed day 06–18 / night 18–06 for v1).
- Robust scenario rerank over the schedule space (robust runs on the **constant** stage 1; the schedule is
  a local refine of an already-robust-feasible constant — see §4.3).
- CMA-ES / full 6-D coarse-to-fine beam.

## 3. Decisions locked during brainstorming

| Question | Decision |
|---|---|
| First B increment | **Time-block (day/night)**, not per-zone/per-hall. |
| Search | **Warm-start**: constant optimum (stage 1) → local day/night refine (stage 2). |
| Blocks | **2 fixed**: day 06:00–18:00, night 18:00–06:00 (local SGT). |
| Activation | **Opt-in** `PlanRequest.time_block` (default off). |
| Robust | Runs on the **constant** (stage 1); schedule refined only from a robust-feasible constant. |
| Acceptance | **Unit proof** + an **optional, marked** 1-day Docker smoke (BCVTB is flaky). |

## 4. Component design

### 4.1 Schedule model (`planner/schedule.py`, new)

```python
@dataclass(frozen=True)
class TimeBlock:
    label: str          # "day" | "night"
    start_hour: int     # inclusive local hour [0,24)
    end_hour: int       # exclusive; end <= start means it wraps midnight (night 18->06)
    def contains(self, hour: int) -> bool: ...   # handles wrap

@dataclass(frozen=True)
class WeeklySchedule:
    blocks: tuple[TimeBlock, ...]
    setpoints: tuple[Setpoints, ...]             # parallel to blocks, same length
    def block_for_hour(self, hour: int) -> int:  # index of the block covering `hour`
        ...

DEFAULT_BLOCKS = (TimeBlock("day", 6, 18), TimeBlock("night", 18, 6))
```

`block_for_hour` returns the index of the block whose `contains(hour)` is true (blocks partition the day;
on overlap the first match wins). A constant plan is representable as a 1-block schedule, so the
objective/safety code never needs to special-case schedules.

### 4.2 Oracle schedule path (`planner/oracle_worker.py`, `planner/oracle.py`)

- `EvalTask` gains an optional `schedule` payload — a picklable representation: a tuple of per-block
  `(sat, flow, chwst)` plus the block boundaries `(label, start_hour, end_hour)`. `candidate` (the constant
  trio) stays for back-compat; `schedule` takes precedence when set.
- `run_episode_with_samples` (and `run_episode`): when a schedule is present, compute the per-step action.
  The env's run period starts at `week_start 00:00`; for step `i`,
  `local_hour = floor(i * hours_per_step) % 24`, pick the block via `block_for_hour`, and
  `action = broadcaster.expand(Setpoints(*schedule_setpoints[block]))`. With no schedule, the existing fixed
  action is used (zero behavior change for constant plans).
- `ParallelEnvOracle.evaluate_schedules(schedules: list[WeeklySchedule], forecast) -> list[WeeklyKPI]`
  mirrors `evaluate` but builds schedule-carrying `EvalTask`s. The hard inlet cap is enforced **every step**
  across both blocks (KPI aggregation is unchanged — it already scans all steps).

### 4.3 Warm-start two-stage search (`planner/schedule_search.py`, new)

`refine_schedule(constant: Setpoints, evaluator, weights, forecast, calibration, blocks=DEFAULT_BLOCKS,
levels=2) -> ScheduleResult` (`ScheduleResult` = `{schedule, kpi, kpi_raw}`). The initial per-control
perturbation step is ¼ of each control's `DEFAULT_SEARCH_SPACE` range (e.g. SAT range 6 °C → 1.5 °C),
halved each of `levels` refine levels:

1. Seed `schedule = WeeklySchedule(blocks, (constant, constant))` (identical blocks == the constant plan).
2. Generate a **local neighborhood**: for each block independently, perturb each control (SAT/flow/CHWST)
   by ±`step` within `DEFAULT_SEARCH_SPACE` bounds (coarse-to-fine, halving `step` per level, like the beam
   refine). Each candidate is a full `WeeklySchedule`; the seed `(constant, constant)` is always included.
3. `evaluator.evaluate_schedules(candidates, forecast)` → KPIs; apply `calibration.apply` (if any) and
   `objective.score` with the margin-adjusted `weights` (the same k·σ pre-tighten as stage 1). Keep the
   best **feasible** schedule; ties/infeasible fall back to the seed `(constant, constant)` — so the
   schedule is **never worse than the constant**.

**Pipeline integration (`planner/pipeline.py`):** after the existing constant beam + robust gate set
`best, kpi, status`, if `request.time_block` AND `status == "pending_approval"` (robust-feasible constant),
call `refine_schedule(best, …)` → the schedule winner; set the recommendation's `schedule` block and mirror
the **day** block into top-level `setpoints`. If the constant is `blocked_unsafe`/`infeasible_fallback`,
skip the refine (stay constant). `beam_search.py` and `robust.py` are untouched.

### 4.4 Recommendation schema 1.5 + opt-in (`planner/recommendation.py`, `planner/pipeline.py`)

- `PlanRequest.time_block: bool = False`; threaded from `webapp/jobs.py::run_plan_job` via
  `params.get("time_block", False)`.
- `build_recommendation(schedule=None)`: when a schedule is given, add
  `rec["schedule"] = {"cadence": "time-block", "blocks": [{"label","start_hour","end_hour",
  "setpoints": {sat,flow,chwst}}, …]}` and bump `schema_version` to **1.5**. Top-level `setpoints` mirrors
  the day block (back-compat for the 3D view / dashboard). `inlet_forecast_margin`/`k_sigma` (1.4) and the
  rest remain.

### 4.5 UI (`frontend/src/{api.ts, pages/NewPlan.tsx, pages/Review.tsx}`)

- `api.ts`: `PlanParams.time_block?: boolean`; `Recommendation.schedule?` typed.
- **New Plan:** a "Day/night setpoints" checkbox → `time_block: true` in the POST.
- **Review:** when `recommendation.schedule` exists, a **Schedule** card — a small table of day vs night
  SAT/flow/CHWST. No 3D changes; the existing per-step trajectory chart already shows the day/night
  structure in the inlet/power trace.

## 5. Data-contract changes

- `recommendation.json`: `schema_version` → **1.5**; new `schedule` block (above) when time-block is on;
  top-level `setpoints` mirrors the day block. Constant plans are unchanged (schema ≤ 1.4).
- `PlanParams`/`PlanRequest`: new `time_block: bool` (default false).
- New env-eval path `evaluate_schedules`; `EvalTask.schedule`.

## 6. Error handling

- Time-block off (default) → identical to today (no schedule, no extra E+ runs).
- A schedule candidate that is infeasible (any block breaches) is dropped by `objective.score`; if **all**
  refine candidates are infeasible, `refine_schedule` returns the seed `(constant, constant)` — i.e. the
  already-robust constant plan — so the recommendation never degrades below the constant.
- `block_for_hour` always returns a valid index (the default blocks partition 24 h, wrap handled); a
  malformed custom block set raises at construction (not in this tier — blocks are fixed).
- Stage 2 only runs when the constant is robust-feasible, so the schedule inherits the robust gate's safety.

## 7. Testing strategy

**Unit (no EnergyPlus):**
- `schedule`: `TimeBlock.contains` incl. wrap (night 18→06 contains 23 and 02, not 12); `block_for_hour`
  for 0..23 with the default blocks; `WeeklySchedule` length invariant.
- per-step action selection: a fake env records the action per step; assert day-hours get the day action
  and night-hours the night action (drive `run_episode_with_samples` with a 2-block schedule + a fake env
  whose step count spans >24 h).
- `schedule_search.refine_schedule` against a `MockEvaluator.evaluate_schedules`: (a) on a surface that
  rewards a day/night split (night cheaper), it returns a non-constant schedule; (b) on a flat surface it
  returns the seed and is **never worse** than the constant; (c) the seed `(constant, constant)` is always
  evaluated.
- `recommendation`: schema 1.5 `schedule` block + top-level day mirror; constant path stays ≤ 1.4.
- `pipeline`: `time_block=True` + a feasible MockEvaluator → rec has a `schedule`; `time_block=False` →
  no schedule; `blocked_unsafe` constant → no schedule even if `time_block=True`.

**Frontend (vitest):** New-Plan toggle sends `time_block`; Review renders the Schedule card from a mocked
recommendation.

**Integration (Docker, marker `integration`, OPTIONAL to run):** one 1-day time-block plan emits a
`schedule` recommendation and (via a captured trajectory) the action differs between day and night hours.
Kept minimal; running it is optional given BCVTB flakiness — the unit tests are the proof.

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **B1** | `planner/schedule.py` (`TimeBlock`, `WeeklySchedule`, `DEFAULT_BLOCKS`) + tests | the schedule model |
| **B2** | oracle schedule path: `EvalTask.schedule` + per-step action in `run_episode_with_samples` + `evaluate_schedules` (+ `MockEvaluator.evaluate_schedules`) | per-step day/night actuation |
| **B3** | `planner/schedule_search.py::refine_schedule` (warm-start, never-worse) + tests | the stage-2 search |
| **B4** | `pipeline.py` wires stage 2 (time_block + robust-feasible) → schedule; `recommendation.py` schema 1.5 + day mirror; `PlanRequest.time_block`; `jobs.py` threads `time_block` | end-to-end planner |
| **B5** | frontend: New-Plan toggle + Review Schedule card + `api.ts` types (+ vitest) | operator UI |
| **B6** | optional Docker smoke: 1-day time-block plan emits a schedule + day≠night action | real-E+ acceptance |

B1–B4 deliver the planner; B5 the UI; B6 the optional proof.

## 9. Reference file index

- Schedule + search: `planner/schedule.py` (new), `planner/schedule_search.py` (new),
  `planner/types.py` (`Setpoints`, `DEFAULT_SEARCH_SPACE`), `planner/objective.py` (score/is_feasible reuse),
  `planner/mock_evaluator.py` (`evaluate_schedules`).
- Oracle: `planner/oracle_worker.py` (`EvalTask`, `run_episode_with_samples`), `planner/oracle.py`
  (`evaluate_schedules`), `planner/broadcast.py` (`BroadcastPolicy.expand`).
- Pipeline/contract: `planner/pipeline.py` (`PlanRequest`, `run_weekly_plan`), `planner/recommendation.py`
  (schema 1.5), `webapp/jobs.py` (`run_plan_job` threads `time_block`).
- UI: `frontend/src/{api.ts, pages/NewPlan.tsx, pages/Review.tsx}`.
- Integration: `tests/integration/test_time_block.py` (new, marked).
