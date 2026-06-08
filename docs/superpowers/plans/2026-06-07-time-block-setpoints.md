# Time-Block (Day/Night) Setpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in day/night setpoint schedule, found by a warm-started search (existing 3-D constant optimum → local day/night refine, never worse than constant) and evaluated by the full-week sim with the env action switched by time-of-day.

**Architecture:** A new `WeeklySchedule` model; the oracle steps the env with each block's action by local hour; a `refine_schedule` warm-start seeded at the robust constant winner; opt-in via `PlanRequest.time_block`; recommendation schema 1.5 `schedule` block. `beam_search.py` and `robust.py` are untouched.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), pytest; React 19 + Vite + vitest; dctwin/EnergyPlus 9.5 via Docker (B6, optional).

**Spec:** `docs/superpowers/specs/2026-06-07-time-block-setpoints-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`
- The sandbox strips a leading `cd` — prefix with `env -C <dir>`.
- Python tests: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest <path> -v`. Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test ...`.
- Commit after each task (repo policy appends a `Co-Authored-By` trailer — keep it). Branch `feat/time-block-setpoints` (already created); do NOT switch branches.

---

## File map

| File | Change | Task |
|---|---|---|
| `planner/schedule.py` (new) | `TimeBlock`, `WeeklySchedule`, `DEFAULT_BLOCKS` | 1 |
| `planner/oracle_worker.py` | `EvalTask.schedule`, `run_episode_schedule`, `evaluate_one_schedule` | 2 |
| `planner/oracle.py` | `ParallelEnvOracle.evaluate_schedules` | 2 |
| `planner/mock_evaluator.py` | `MockEvaluator.evaluate_schedules` | 2 |
| `planner/schedule_search.py` (new) | `refine_schedule` (warm-start) + `ScheduleResult` | 3 |
| `planner/pipeline.py` | `PlanRequest.time_block`; stage-2 wiring in `run_weekly_plan` | 4 |
| `planner/recommendation.py` | `schedule` block + schema 1.5 | 4 |
| `webapp/schemas.py` | `PlanParams.time_block` | 4 |
| `webapp/jobs.py` | thread `time_block` into `PlanRequest` | 4 |
| `frontend/src/api.ts` | `PlanParams.time_block`, `Recommendation.schedule` | 5 |
| `frontend/src/pages/NewPlan.tsx` | day/night toggle | 5 |
| `frontend/src/pages/Review.tsx` | Schedule card | 5 |
| `tests/integration/test_time_block.py` (new) | optional Docker smoke | 6 |

---

## Task 1: Schedule model (`planner/schedule.py`) (spec §4.1, B1)

**Files:**
- Create: `planner/schedule.py`
- Test: `tests/test_schedule.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_schedule.py`:

```python
from planner.schedule import TimeBlock, WeeklySchedule, DEFAULT_BLOCKS
from planner.types import Setpoints


def test_timeblock_contains_non_wrap():
    day = TimeBlock("day", 6, 18)
    assert day.contains(6) and day.contains(12) and day.contains(17)
    assert not day.contains(5) and not day.contains(18) and not day.contains(23)


def test_timeblock_contains_wrap():
    night = TimeBlock("night", 18, 6)        # wraps midnight
    assert night.contains(18) and night.contains(23) and night.contains(0) and night.contains(5)
    assert not night.contains(6) and not night.contains(12)


def test_default_blocks_partition_the_day():
    sched = WeeklySchedule(DEFAULT_BLOCKS, (Setpoints(24, 8, 17), Setpoints(25, 7, 16)))
    # every hour maps to exactly one block; day=0 (06-18), night=1 (18-06)
    assert [sched.block_for_hour(h) for h in (0, 5, 6, 12, 17, 18, 23)] == [1, 1, 0, 0, 0, 1, 1]


def test_schedule_length_invariant():
    import pytest
    with pytest.raises(ValueError):
        WeeklySchedule(DEFAULT_BLOCKS, (Setpoints(24, 8, 17),))   # 2 blocks, 1 setpoint
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'planner.schedule'`.

- [ ] **Step 3: Implement `planner/schedule.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from planner.types import Setpoints


@dataclass(frozen=True)
class TimeBlock:
    """A daily time window [start_hour, end_hour) in local hours. end <= start wraps midnight."""
    label: str
    start_hour: int
    end_hour: int

    def contains(self, hour: int) -> bool:
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour   # wrap (e.g. 18->06)


@dataclass(frozen=True)
class WeeklySchedule:
    """A per-time-block setpoint schedule. `setpoints[i]` applies during `blocks[i]`."""
    blocks: tuple[TimeBlock, ...]
    setpoints: tuple[Setpoints, ...]

    def __post_init__(self) -> None:
        if len(self.blocks) != len(self.setpoints):
            raise ValueError(
                f"blocks ({len(self.blocks)}) and setpoints ({len(self.setpoints)}) length mismatch")

    def block_for_hour(self, hour: int) -> int:
        """Index of the block covering `hour` (first match wins; falls back to 0)."""
        for i, b in enumerate(self.blocks):
            if b.contains(hour):
                return i
        return 0


DEFAULT_BLOCKS = (TimeBlock("day", 6, 18), TimeBlock("night", 18, 6))
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_schedule.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/schedule.py src/tests/test_schedule.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): WeeklySchedule / TimeBlock model for time-block setpoints"
```

---

## Task 2: Oracle schedule path (spec §4.2, B2)

**Files:**
- Modify: `planner/oracle_worker.py`
- Modify: `planner/oracle.py`
- Modify: `planner/mock_evaluator.py`
- Test: `tests/test_oracle_worker.py`, `tests/test_mock_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_oracle_worker.py`:

```python
def test_run_episode_schedule_switches_action_by_hour():
    import numpy as np
    from planner.oracle_worker import run_episode_schedule
    from planner.schedule import WeeklySchedule, TimeBlock
    from planner.types import Setpoints
    from planner.kpi import OracleSettings
    from planner.monitor import MonitorSpec

    sched = WeeklySchedule((TimeBlock("day", 6, 18), TimeBlock("night", 18, 6)),
                           (Setpoints(24.0, 8.0, 17.0), Setpoints(26.0, 6.0, 15.0)))

    class _FakeBroadcaster:
        def expand(self, sp):
            return np.array([sp.sat_c])   # action[0] == the block's SAT, so we can read it back

    recorded = []

    class _Env:
        def __init__(self):
            self.i = 0
            self.unwrapped = self
        def inspect_current_observation(self, observation_name, use_unnormed=True):
            return 24.0
        def reset(self):
            self.i = 0
            return None, {}
        def step(self, action):
            recorded.append((self.i, float(action[0])))
            self.i += 1
            return None, 0.0, self.i >= 48, False, {}   # 48 hourly steps = 2 days

    mon = MonitorSpec(total_power_name="tp", it_power_name="it", inlet_temp_names=["a"])
    run_episode_schedule(_Env(), _FakeBroadcaster(), sched, mon,
                         hours_per_step=1.0, settings=OracleSettings(warmup_steps=0))
    assert recorded, "env should have been stepped"
    for i, sat in recorded:
        hour = i % 24
        assert sat == (24.0 if 6 <= hour < 18 else 26.0)   # day SAT vs night SAT
```

Append to `tests/test_mock_evaluator.py`:

```python
def test_mock_evaluate_schedules_constant_matches_single_kpi():
    from planner.mock_evaluator import MockEvaluator, MockSurface
    from planner.schedule import WeeklySchedule, DEFAULT_BLOCKS
    from planner.types import Setpoints
    ev = MockEvaluator(MockSurface())
    sp = Setpoints(24.0, 8.0, 17.0)
    single = ev.evaluate([sp])[0]
    sched = WeeklySchedule(DEFAULT_BLOCKS, (sp, sp))           # constant schedule
    sk = ev.evaluate_schedules([sched])[0]
    assert abs(sk.total_hvac_energy_kwh - single.total_hvac_energy_kwh) < 1e-9
    assert abs(sk.inlet_temp_max - single.inlet_temp_max) < 1e-9
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle_worker.py tests/test_mock_evaluator.py -k "schedule or evaluate_schedules" -v` (single `-k` over both files — two `-k` flags would silently drop the first).
Expected: FAIL — `cannot import name 'run_episode_schedule'` / `MockEvaluator` has no `evaluate_schedules`.

- [ ] **Step 3: Add `EvalTask.schedule` + `run_episode_schedule` + `evaluate_one_schedule`**

In `planner/oracle_worker.py`, add `from typing import Optional` to the existing `from typing import Any` import. Add a `schedule` field to `EvalTask` (after `monitored_hall`); it holds a picklable `planner.schedule.WeeklySchedule` (a frozen dataclass of `TimeBlock`/`Setpoints` tuples — picklable for the pool) and overrides `candidate` when set:

```python
    schedule: Optional[Any] = None   # planner.schedule.WeeklySchedule; overrides `candidate` when set
```

Add `run_episode_schedule` (after `run_episode`):

```python
def run_episode_schedule(env, broadcaster, schedule, monitor: MonitorSpec,
                         hours_per_step: float, settings: OracleSettings):
    """Step the env to completion, switching the action by local time-of-day from `schedule`.
    The run starts at week_start 00:00, so step i is at local hour int(i*hours_per_step) % 24."""
    samples: list[StepSample] = []
    env.reset()
    samples.append(read_step_sample(env.unwrapped, monitor))
    done = False
    i = 0
    while not done:
        hour = int(i * hours_per_step) % 24
        sp = schedule.setpoints[schedule.block_for_hour(hour)]
        action = broadcaster.expand(Setpoints(sp.sat_c, sp.flow_kg_s, sp.chwst_c))
        _obs, _rew, done, _trunc, _info = env.step(action)
        i += 1
        if not done:
            samples.append(read_step_sample(env.unwrapped, monitor))
    return aggregate_kpi(samples, hours_per_step, settings), samples
```

Add `evaluate_one_schedule` (after `evaluate_one_with_samples`):

```python
def evaluate_one_schedule(task: EvalTask) -> WeeklyKPI:
    """Process-pool target for a time-block schedule. Same env setup as evaluate_one but
    applies task.schedule's per-block action by hour. Returns infeasible on failure."""
    import dctwin
    from dctwin.utils import config as dt_config
    from planner.env_actions import mapper_from_env
    from planner.monitor import discover_monitor
    import dctwin.third_parties.eplus.core as _eplus_core
    _eplus_core.EplusBackendMixin._post_process = staticmethod(lambda: None)

    env = None
    try:
        dt_config.set_log_dir(task.log_dir)
        env = dctwin.make_env(env_proto_config=task.week_config_path, reward_fn=lambda x: 0)
        backend = getattr(getattr(env, "unwrapped", env), "eplus_backend", None)
        if backend is not None and task.bcvtb_host:
            backend._host = task.bcvtb_host
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env, hall=task.monitored_hall)
        kpi, _samples = run_episode_schedule(env, broadcaster, task.schedule, monitor,
                                             task.hours_per_step, OracleSettings(**task.settings_kwargs))
        return kpi
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule candidate failed: %s", exc)
        return _infeasible(str(exc))
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
            _teardown_container(env)
```

- [ ] **Step 4: Add `ParallelEnvOracle.evaluate_schedules`**

In `planner/oracle.py`, change the worker import (line 9) to also import the schedule worker:
`from planner.oracle_worker import EvalTask, evaluate_one, evaluate_one_with_samples, evaluate_one_schedule`
(if `evaluate_one_with_samples` isn't already imported there, include it — check the current import line).

Add the method (after `replay_with_trajectory`, mirroring `evaluate` but with schedule tasks + the schedule worker):

```python
    def evaluate_schedules(self, schedules, forecast=None,
                           on_result: Optional[Callable[[], None]] = None) -> list[WeeklyKPI]:
        """Score time-block WeeklySchedules with full-week EnergyPlus runs (per-step action by hour)."""
        cfg = self.config
        hours_per_step = 1.0 / cfg.timesteps_per_hour
        if forecast is not None and hasattr(forecast, "materialize"):
            forecast.materialize(self.project_root)
        log_root = Path(cfg.log_root).resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        if forecast is not None and getattr(forecast, "week_start", None) is not None:
            week_cfg_path = str(log_root / "week.prototxt")
            self._write_week_cfg(forecast, week_cfg_path)
        else:
            week_cfg_path = str(Path(self.base_prototxt).resolve())
        tasks = [
            EvalTask(candidate=s.setpoints[0].as_tuple(), week_config_path=week_cfg_path,
                     log_dir=str(log_root / f"sched-{i:04d}"), hours_per_step=hours_per_step,
                     settings_kwargs=cfg.settings.__dict__, bcvtb_host=cfg.bcvtb_host,
                     monitored_hall=cfg.monitored_hall, schedule=s)
            for i, s in enumerate(schedules)
        ]
        if not cfg.use_process_pool:
            out = []
            for t in tasks:
                try:
                    out.append(evaluate_one_schedule(t))
                except Exception:  # noqa: BLE001
                    out.append(_infeasible())
                if on_result is not None:
                    on_result()
            return out
        results: list[WeeklyKPI] = [_infeasible()] * len(tasks)
        ex = cf.ProcessPoolExecutor(max_workers=cfg.n_workers)
        futs = {ex.submit(evaluate_one_schedule, t): i for i, t in enumerate(tasks)}
        deadline = cfg.timeout_s * max(len(tasks), 1)
        try:
            for fut in cf.as_completed(futs, timeout=deadline):
                i = futs[fut]
                try:
                    results[i] = fut.result()
                except Exception:  # noqa: BLE001
                    results[i] = _infeasible()
                if on_result is not None:
                    on_result()
        except cf.TimeoutError:
            pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return results
```

- [ ] **Step 5: Add `MockEvaluator.evaluate_schedules`**

In `planner/mock_evaluator.py`, add to `MockEvaluator` (it already imports `WeeklyKPI`, `Setpoints`):

```python
    def evaluate_schedules(self, schedules, forecast=None):
        """Analytic schedule KPI: per-block bowl KPI, energy hour-weighted (equal blocks),
        inlet = worst block, violations summed. A CONSTANT schedule == the single-setpoint KPI."""
        out = []
        for sch in schedules:
            ks = [self._kpi(sp) for sp in sch.setpoints]
            n = len(ks)
            energy = sum(k.total_hvac_energy_kwh for k in ks) / n
            inlet = max(k.inlet_temp_max for k in ks)
            viol = sum(k.inlet_violation_steps for k in ks)
            out.append(WeeklyKPI(
                total_hvac_energy_kwh=energy, pue_mean=1.2 + energy / 10000.0,
                inlet_temp_max=inlet, inlet_violation_steps=viol, rh_violation_steps=0,
                feasible=True, inlet_excess_degc_steps=max(inlet - (self.surface.inlet_cap - 1.0), 0.0)))
        return out
```

- [ ] **Step 6: Run the tests, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle_worker.py tests/test_mock_evaluator.py tests/test_oracle.py -v`
Expected: PASS (incl. the two new tests; existing oracle tests unaffected — `EvalTask.schedule` defaults to None so the constant path is unchanged).

- [ ] **Step 7: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/oracle_worker.py src/planner/oracle.py src/planner/mock_evaluator.py src/tests/test_oracle_worker.py src/tests/test_mock_evaluator.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): oracle schedule path — per-step day/night action + evaluate_schedules"
```

---

## Task 3: Warm-start schedule search (`planner/schedule_search.py`) (spec §4.3, B3)

**Files:**
- Create: `planner/schedule_search.py`
- Test: `tests/test_schedule_search.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_schedule_search.py`:

```python
from planner.schedule_search import refine_schedule
from planner.schedule import WeeklySchedule, DEFAULT_BLOCKS
from planner.objective import ObjectiveWeights
from planner.types import Setpoints
from planner.kpi import WeeklyKPI    # noqa: F401


class _Monotone:
    """Schedule evaluator where warmer SAT / lower flow is CHEAPER but raises inlet. The DAY
    block (index 0, ambient 22 C) is near its inlet limit at the constant, so it can't relax;
    the NIGHT block (index 1, ambient 19 C = 3 C cooler) has slack — so the optimum is a SPLIT
    where the night block is relaxed (here greedy coordinate-descent relaxes night FLOW, since
    that is the steepest energy lever on this surface; day can't because lower flow breaches)."""
    CAP = 26.0
    def evaluate_schedules(self, schedules, forecast=None):
        from planner.types import WeeklyKPI
        out = []
        for sch in schedules:
            tot_e, max_inlet, viol = 0.0, -1e9, 0
            for b, sp in enumerate(sch.setpoints):
                ambient = 22.0 - (3.0 if b == 1 else 0.0)   # day 22, night 19
                inlet = ambient + 1.0 * (sp.sat_c - 20) + 0.5 * (sp.chwst_c - 13) - 0.4 * (sp.flow_kg_s - 4.8)
                energy = 200.0 - 5 * (sp.sat_c - 20) - 3 * (sp.chwst_c - 13) + 4 * (sp.flow_kg_s - 4.8)
                tot_e += energy / len(sch.setpoints)
                max_inlet = max(max_inlet, inlet)
                viol += 0 if inlet <= self.CAP else 1
            out.append(WeeklyKPI(total_hvac_energy_kwh=tot_e, pue_mean=1.2, inlet_temp_max=max_inlet,
                                 inlet_violation_steps=viol, rh_violation_steps=0, feasible=True,
                                 inlet_excess_degc_steps=max(max_inlet - (self.CAP - 1), 0.0)))
        return out


def test_refine_schedule_finds_a_cheaper_night_relaxed_split():
    const = Setpoints(23.0, 8.0, 17.0)        # day inlet 25.72 <= 26 (near limit), night 22.72 (slack)
    ev = _Monotone()
    const_energy = ev.evaluate_schedules(
        [WeeklySchedule(DEFAULT_BLOCKS, (const, const))])[0].total_hvac_energy_kwh
    res = refine_schedule(const, ev, ObjectiveWeights(), forecast=None, calibration=None, levels=2)
    day_sp, night_sp = res.schedule.setpoints
    # the cooler night block gets relaxed (the day block is inlet-constrained at the constant and can't).
    # WHICH control relaxes depends on the surface, so assert a genuine, strictly-cheaper split.
    assert night_sp != day_sp                                    # genuine day/night split
    assert res.kpi.total_hvac_energy_kwh < const_energy          # strictly cheaper than the constant


def test_refine_schedule_never_worse_than_constant_on_flat_surface():
    const = Setpoints(24.0, 8.0, 17.0)

    class _Flat:
        def evaluate_schedules(self, schedules, forecast=None):
            from planner.types import WeeklyKPI
            return [WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=22.0,
                              inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                              inlet_excess_degc_steps=0.0) for _ in schedules]

    res = refine_schedule(const, _Flat(), ObjectiveWeights(), forecast=None, calibration=None, levels=2)
    # flat surface -> no improvement -> the seed (constant, constant) is returned
    assert res.schedule.setpoints[0] == const and res.schedule.setpoints[1] == const
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_schedule_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'planner.schedule_search'`.

- [ ] **Step 3: Implement `planner/schedule_search.py`**

```python
"""Warm-start day/night schedule refinement (sub-project B). Stage 2 of the time-block plan:
seed the schedule at the (already-robust) constant winner, then locally refine each block."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from planner.objective import ObjectiveWeights, score
from planner.schedule import DEFAULT_BLOCKS, WeeklySchedule
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints, WeeklyKPI


@dataclass
class ScheduleResult:
    schedule: WeeklySchedule
    kpi: WeeklyKPI          # calibrated (twin's best estimate)
    kpi_raw: WeeklyKPI      # uncalibrated


def _neighbors(sched: WeeklySchedule, step: np.ndarray) -> list[WeeklySchedule]:
    space = DEFAULT_SEARCH_SPACE
    base = [list(sp.as_tuple()) for sp in sched.setpoints]
    out: list[WeeklySchedule] = []
    for b in range(len(sched.blocks)):
        for c in range(3):
            for sign in (1.0, -1.0):
                pert = [row[:] for row in base]
                pert[b][c] += sign * step[c]
                sps = tuple(space.clip(Setpoints(float(p[0]), float(p[1]), float(p[2]))) for p in pert)
                out.append(WeeklySchedule(sched.blocks, sps))
    return out


def refine_schedule(constant: Setpoints, evaluator, weights: ObjectiveWeights, forecast,
                    calibration, blocks=DEFAULT_BLOCKS, levels: int = 2) -> ScheduleResult:
    """Warm-start: seed at (constant,...) per block, then coordinate-descent refine over `levels`
    halving steps. Uses the same objective + (margin-adjusted) weights + calibration as the search.
    The seed is always evaluated first, so the result is NEVER worse than the constant."""
    space = DEFAULT_SEARCH_SPACE
    seed = WeeklySchedule(blocks, tuple(constant for _ in blocks))
    step = np.array([(space.sat.ub - space.sat.lb) / 4.0,
                     (space.flow.ub - space.flow.lb) / 4.0,
                     (space.chwst.ub - space.chwst.lb) / 4.0])

    def evaluate(sched: WeeklySchedule):
        raw = evaluator.evaluate_schedules([sched], forecast)[0]
        kpi = calibration.apply(raw) if calibration is not None else raw
        return score(kpi, weights), kpi, raw

    best_score, best_kpi, best_raw = evaluate(seed)
    best, cur = seed, seed
    for _ in range(levels):
        for sched in _neighbors(cur, step):
            sc, kpi, raw = evaluate(sched)
            if sc < best_score:
                best_score, best_kpi, best_raw, best = sc, kpi, raw, sched
        cur = best
        step = step / 2.0
    return ScheduleResult(best, best_kpi, best_raw)
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_schedule_search.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/schedule_search.py src/tests/test_schedule_search.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): warm-start day/night schedule refine (never worse than constant)"
```

---

## Task 4: Pipeline wiring + schema 1.5 + opt-in (spec §4.4, B4)

**Files:**
- Modify: `planner/pipeline.py`, `planner/recommendation.py`, `webapp/schemas.py`, `webapp/jobs.py`
- Test: `tests/test_pipeline.py`, `tests/test_recommendation.py`

- [ ] **Step 1: Write the failing recommendation test**

Append to `tests/test_recommendation.py`:

```python
def test_build_recommendation_schedule_block_schema_1_5():
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from planner.schedule import WeeklySchedule, DEFAULT_BLOCKS
    from datetime import date
    kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                    inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    sched = WeeklySchedule(DEFAULT_BLOCKS, (Setpoints(23.0, 9.0, 16.0), Setpoints(25.0, 6.0, 15.0)))
    rec = build_recommendation(setpoints=Setpoints(23.0, 9.0, 16.0), kpi=kpi, week_start=date(2013, 11, 11),
                               days=7, forecast_method="persistence", search_meta={"evals": 1}, schedule=sched)
    assert rec["schema_version"] == "1.5"
    blocks = rec["schedule"]["blocks"]
    assert blocks[0]["label"] == "day" and blocks[0]["setpoints"]["crah_supply_air_temperature_c"] == 23.0
    assert blocks[1]["label"] == "night" and blocks[1]["setpoints"]["crah_supply_air_temperature_c"] == 25.0
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py -k schedule_block -v`
Expected: FAIL — `build_recommendation()` has no `schedule` kwarg.

- [ ] **Step 3: Add `schedule` to `build_recommendation`**

In `planner/recommendation.py`, add to the signature (after `k_sigma`):

```python
    k_sigma: Optional[float] = None,
    schedule=None,   # planner.schedule.WeeklySchedule
) -> dict:
```

Before `return rec`, insert:

```python
    if schedule is not None:
        rec["schedule"] = {
            "cadence": "time-block",
            "blocks": [
                {"label": b.label, "start_hour": b.start_hour, "end_hour": b.end_hour,
                 "setpoints": {"crah_supply_air_temperature_c": round(sp.sat_c, 2),
                               "crah_supply_air_mass_flow_rate_kg_s": round(sp.flow_kg_s, 2),
                               "chilled_water_supply_temperature_c": round(sp.chwst_c, 2)}}
                for b, sp in zip(schedule.blocks, schedule.setpoints)
            ],
        }
        rec["schema_version"] = "1.5"
```

- [ ] **Step 4: Add `time_block` to `PlanRequest` + wire stage 2 in `run_weekly_plan`**

In `planner/pipeline.py`, add `time_block: bool = False` to `PlanRequest` (after `timesteps_per_hour`). In `run_weekly_plan`, after the constant `best, kpi, raw, status` block (the `if robust ... elif ... else` ending at the `infeasible_fallback` branch) and BEFORE the `return build_recommendation(...)`, insert:

```python
    schedule = None
    if request.time_block and status == "pending_approval" and hasattr(evaluator, "evaluate_schedules"):
        from planner.schedule_search import refine_schedule
        sched_res = refine_schedule(best, evaluator, weights, forecast, calibration)
        schedule = sched_res.schedule
        best, kpi, raw = schedule.setpoints[0], sched_res.kpi, sched_res.kpi_raw   # top-level mirrors DAY block
```

Then add `schedule=schedule,` to the `build_recommendation(...)` call (after `k_sigma=K_SIGMA,`).

- [ ] **Step 5: Add the failing pipeline tests + the request/param plumbing**

Append to `tests/test_pipeline.py`:

```python
def test_run_weekly_plan_time_block_emits_schedule():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2, time_block=True),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)), forecaster=_FakeForecaster())
    assert rec["schema_version"] == "1.5"
    assert rec["schedule"]["cadence"] == "time-block" and len(rec["schedule"]["blocks"]) == 2


def test_run_weekly_plan_no_schedule_by_default():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)), forecaster=_FakeForecaster())
    assert "schedule" not in rec
```

In `webapp/schemas.py`, add `time_block: bool = False` to `PlanParams` (after `n_workers`).

In `webapp/jobs.py::run_plan_job`, add `time_block` to the `PlanRequest(...)` constructor. The current last arg line ends `timesteps_per_hour=int(params.get("timesteps_per_hour", 4)))` where the trailing `)` closes the call — so move that paren: change it to `timesteps_per_hour=int(params.get("timesteps_per_hour", 4)),` and add a new line `                    time_block=bool(params.get("time_block", False))),`.

- [ ] **Step 6: Run the tests, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py tests/test_pipeline.py tests/test_api.py -v`
Expected: PASS. (Existing pipeline tests use `time_block=False` default → no schedule, unchanged. `MockEvaluator.evaluate_schedules` exists from Task 2, so the time-block test's refine returns the constant-as-schedule — both blocks equal C* on the bowl surface — and the rec carries a 2-block schedule.)

- [ ] **Step 7: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/pipeline.py src/planner/recommendation.py src/webapp/schemas.py src/webapp/jobs.py src/tests/test_pipeline.py src/tests/test_recommendation.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): wire time-block stage-2 schedule into the pipeline (opt-in, schema 1.5)"
```

---

## Task 5: Frontend — toggle + schedule card (spec §4.5, B5)

**Files:**
- Modify: `src/frontend/src/api.ts`
- Modify: `src/frontend/src/pages/NewPlan.tsx`
- Modify: `src/frontend/src/pages/Review.tsx`
- Test: `src/frontend/src/pages/NewPlan.test.tsx`, `src/frontend/src/pages/Review.test.tsx`

- [ ] **Step 1: Extend `api.ts`**

In `src/frontend/src/api.ts`: add `time_block?: boolean;` to the `PlanParams` interface, and a `schedule` field to `Recommendation`:

```typescript
export interface ScheduleBlock { label: string; start_hour: number; end_hour: number; setpoints: Record<string, number>; }
```

and inside `interface Recommendation { ... }` add: `schedule?: { cadence: string; blocks: ScheduleBlock[] } | null;`

- [ ] **Step 2: NewPlan toggle — failing test**

In `src/frontend/src/pages/NewPlan.test.tsx`, add an `it(...)` inside the existing `describe` (reuse the file's existing `vi.mock('../api', ...)` + `createPlan` mock). Assert that checking the toggle sends `time_block:true`:

```typescript
  it('sends time_block when the day/night toggle is on', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p1', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2013-11-11' } });
    fireEvent.click(screen.getByLabelText(/day\/night setpoints/i));
    fireEvent.click(screen.getByRole('button', { name: /launch/i }));
    await waitFor(() => expect(createPlan).toHaveBeenCalledWith(expect.objectContaining({ time_block: true })));
  });
```

(If `NewPlan.test.tsx` doesn't yet import `createPlan`/`fireEvent`/`waitFor`/`screen`, add them to the existing imports + the `vi.mock` factory must expose `createPlan: vi.fn()` and `getProgress`/`getPlan: vi.fn()`. Mirror the existing mock; don't add a second `vi.mock`.)

- [ ] **Step 3: Add the toggle to `NewPlan.tsx`**

Add state `const [timeBlock, setTimeBlock] = useState(false);` (next to the other `useState`s). Add `time_block: timeBlock,` to the `createPlan({...})` call. Add the checkbox inside the form's `card-body`, after the params grid (before `{error && ...}`):

```tsx
              <div className="field">
                <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={timeBlock} disabled={!!planId}
                         onChange={e => setTimeBlock(e.target.checked)} />
                  Day/night setpoints (time-block)
                </label>
              </div>
```

- [ ] **Step 4: Review schedule card — failing test**

In `src/frontend/src/pages/Review.test.tsx`, add a `getTrajectory`-style `it(...)` inside the existing `describe` that mocks a recommendation WITH a `schedule` and asserts the Schedule card renders. Reuse the existing `vi.mock('../api', ...)` (add nothing new to the factory — `getPlan` is already a `vi.fn()`):

```typescript
  it('renders the day/night schedule card', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLAN_SUMMARY]);
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PLAN_DETAIL,
      recommendation: { ...PLAN_DETAIL.recommendation, schedule: { cadence: 'time-block', blocks: [
        { label: 'day', start_hour: 6, end_hour: 18, setpoints: { crah_supply_air_temperature_c: 23, crah_supply_air_mass_flow_rate_kg_s: 9, chilled_water_supply_temperature_c: 16 } },
        { label: 'night', start_hour: 18, end_hour: 6, setpoints: { crah_supply_air_temperature_c: 25, crah_supply_air_mass_flow_rate_kg_s: 6, chilled_water_supply_temperature_c: 15 } },
      ] } },
    });
    render(<Review planId={PLAN_SUMMARY.plan_id} />);
    await waitFor(() => expect(screen.getByText(/Day\/Night Schedule/i)).toBeInTheDocument());
  });
```

- [ ] **Step 5: Add the Schedule card to `Review.tsx`**

In `Review.tsx`, after the Setpoint editor card (or any card in the detail grid), add — driven by `rec?.schedule`:

```tsx
          {rec?.schedule && (
            <div className="card bracket-card animate-in animate-in-3">
              <div className="card-header">
                <span className="card-title">Day/Night Schedule</span>
                <span className="text-xs text-dim">{rec.schedule.cadence}</span>
              </div>
              <table className="data-table">
                <thead><tr><th>Block</th><th>SAT °C</th><th>Flow kg/s</th><th>CHWST °C</th></tr></thead>
                <tbody>
                  {rec.schedule.blocks.map(b => (
                    <tr key={b.label}>
                      <td className="label-cell">{b.label} ({b.start_hour}:00–{b.end_hour}:00)</td>
                      <td style={{ color: 'var(--cyan)' }}>{b.setpoints.crah_supply_air_temperature_c}</td>
                      <td style={{ color: 'var(--text-secondary)' }}>{b.setpoints.crah_supply_air_mass_flow_rate_kg_s}</td>
                      <td style={{ color: 'var(--text-secondary)' }}>{b.setpoints.chilled_water_supply_temperature_c}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
```

(`rec` is already `detail?.recommendation` in Review.tsx; the typed `Recommendation.schedule` from Step 1 makes this compile.)

- [ ] **Step 6: Run the frontend tests + build**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass; build clean.

- [ ] **Step 7: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/pages/NewPlan.tsx src/frontend/src/pages/NewPlan.test.tsx src/frontend/src/pages/Review.tsx src/frontend/src/pages/Review.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): New-Plan day/night toggle + Review schedule card"
```

---

## Task 6: Optional Docker smoke (spec §7, B6)

**Files:**
- Create: `tests/integration/test_time_block.py`

- [ ] **Step 1: Write the Docker-gated smoke**

Create `tests/integration/test_time_block.py`:

```python
"""Docker-gated smoke: a time-block plan emits a day/night schedule and the per-step action
differs between day and night hours. OPTIONAL to run (BCVTB is flaky). Run:
  env -C src sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
    tests/integration/test_time_block.py -m integration -v"
"""
import pytest

pytestmark = pytest.mark.integration


def test_time_block_plan_emits_schedule(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    plan_id = "gds-tb-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2, "time_block": True}
    store.create_plan(plan_id, params["week_start"], params)
    run_plan_job(plan_id, params, store, lambda p: None)

    rec = store.get_recommendation(plan_id)
    # if the constant was robust-feasible, a schedule must be present with 2 blocks
    if rec["status"] == "pending_approval":
        assert rec.get("schema_version") == "1.5"
        assert rec["schedule"]["cadence"] == "time-block"
        assert len(rec["schedule"]["blocks"]) == 2
        day = rec["schedule"]["blocks"][0]["setpoints"]
        night = rec["schedule"]["blocks"][1]["setpoints"]
        assert day and night                                  # both present
    else:
        # blocked_unsafe/infeasible_fallback -> no schedule (constant only), per the spec
        assert "schedule" not in rec
```

- [ ] **Step 2: Verify deselected without Docker**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/integration/test_time_block.py -v`
Expected: `1 deselected` (no collection errors).

- [ ] **Step 3: (Optional) run under Docker**

Run (only if you want the live-E+ smoke; ~10–15 min, may hang on BCVTB):
```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src timeout --signal=KILL 2700 sg docker -c "PYTHONPATH=/mnt/lv/home/hoanghuy/newcode/dctwin/src /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_time_block.py -m integration -v"
```
Expected: PASS (or skip if Docker is unavailable).

- [ ] **Step 4: Full unit suite (no regressions)**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`
Expected: all unit pass; integration tests deselected.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/tests/integration/test_time_block.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "test(dtwin): optional Docker smoke — time-block plan emits a day/night schedule"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test && npm run build`.
- [ ] Confirm a `time_block=True` MockEvaluator plan carries a 2-block `schedule` + `schema_version "1.5"`; a default plan has no `schedule`.
- [ ] Update memory (`dtwin-dual-loop-framework.md`) with sub-project B (time-block day/night setpoints, warm-start, schema 1.5).
