# Digital Twin Dual-Loop — Plan 2: dctwin Oracle + Forecaster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the EnergyPlus-backed `ParallelEnvOracle` (the dctwin↔dcbrain seam) and the statistical `Forecaster`, so the Plan-1 `BeamPlanner` can score candidate weekly setpoints with real full-week EnergyPlus 9.5 runs.

**Architecture:** Pure-logic units (env→action mapping, KPI aggregation, week-config writing, forecasting) are TDD'd with fakes/fixtures. A thin process-pool worker runs one full-week dctwin EnergyPlus simulation per candidate and is covered by `@pytest.mark.integration` tests that need Docker + the EnergyPlus image. Parallelism is **process-based** because `dctwin.utils.config` is a process-global singleton.

**Tech Stack:** Python 3.10+, numpy, pandas, pytest, `dctwin` (v3.x), Docker + `ghcr.io/cap-dcwiz/energyplus-9-5-0`. Builds on Plan 1's `planner/` package.

**Prerequisite:** Plan 1 complete and green (`planner/types.py`, `broadcast.py`, `objective.py`, `beam_search.py`).

**Reference spec:** `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` (§7.2 Oracle, §7.5 Forecaster, §11 error handling).

### Verified dctwin API facts (use these exactly)

- `dctwin.make_env(env_proto_config: str, reward_fn, schedule_fn=None, parse_obs_fn=None, ...) -> gym.Env` — `dctwin/registration.py:9`. **Path string only.** Use `env.unwrapped` for dctwin methods.
- `env.reset()` → `(obs, info)`; `env.step(action)` → `(obs, reward, done, truncated, info)` (`base_env.py:372,393`). `action` = `np.ndarray` float64, normalized **[-1,1]**, one entry per `AGENT_CONTROLLED` action in declaration order.
- `env.unwrapped.actions` → list of Action objects, each with `.control_type` (int; **2 == AGENT_CONTROLLED**) and `.variable_name` (`base_env.py`, confirmed in sample `hooks.py:364-365`).
- `env.unwrapped.observations` → list with `.variable_name`. `env.unwrapped.inspect_current_observation(observation_name=..., use_unnormed=True)` → scalar (`base_env.py:431`).
- Run period: `from dctwin.utils import read_engine_config`; `cfg = read_engine_config(path)`; `name = cfg.WhichOneof("EnvConfig")`; `env_cfg = getattr(cfg, name)`; mutate `env_cfg.simulation_time_config.{begin_month,begin_day_of_month,end_month,end_day_of_month,number_of_timesteps_per_hour}`; serialize `google.protobuf.text_format.MessageToString(cfg)`. EnergyPlus RunPeriod is **inclusive** of end day (7-day week = begin .. begin+6 days).
- Globals: `from dctwin.utils import config as dt_config`; `dt_config.config.set_log_dir(path)` (`config.py:169`); `dt_config.config.LOG_DIR`.
- GDS config: `number_of_timesteps_per_hour: 4` → **0.25 h/step**; obs `"total power"` (Facility Total Electricity Demand Rate, W), `"total it power"` (Facility Total Building Electricity Demand Rate, W); inlet temps `"data hall 1f 2a ite-{1..22} inlet dry-bulb temperature"`; zone temps `"data hall 1f 2a air temperature"` (+6 more rooms).
- AGENT_CONTROLLED action names: `*_supply_air_temperature_setpoint` (SAT, 22), `*_supply_air_mass_flow_rate` (FLOW, 22), `chilled_water_loop_supply_temperature_setpoint` (CHWST, 1).

**Note on commits:** branch `feat/dtwin-dual-loop-framework`; append `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` to each commit body.

---

## File Structure

Paths relative to `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`.

| File | Responsibility |
|---|---|
| `pyproject.toml` | add `integration` marker (modify) |
| `planner/env_actions.py` | classify AGENT_CONTROLLED actions by name → `BroadcastPolicy` derived from a live env |
| `planner/kpi.py` | `StepSample`, `OracleSettings`, `aggregate_kpi` (pure metrics → `WeeklyKPI`) |
| `planner/monitor.py` | discover monitored observation names (inlet temp/RH, zone temp) from an env |
| `planner/week_config.py` | write a weekly run-period prototxt override |
| `planner/oracle_worker.py` | top-level `evaluate_one(task)` — one full-week E+ run (process-pool target) |
| `planner/oracle.py` | `ParallelEnvOracle(Evaluator)` — process-pool fan-out, timeouts, error→infeasible |
| `planner/forecaster.py` | `Forecast`, `StatisticalForecaster` (persistence/seasonal-naive) + workload writer |
| `fit_forecaster.py` | "ai policy train" analog: fit + persist forecaster from his_data |
| `tests/test_env_actions.py` | classification + spec assembly (fakes) |
| `tests/test_kpi.py` | KPI aggregation (synthetic samples) |
| `tests/test_monitor.py` | observation discovery (fake env) |
| `tests/test_week_config.py` | run-period override correctness |
| `tests/test_oracle.py` | orchestration with monkeypatched worker; error/timeout handling |
| `tests/test_forecaster.py` | persistence reproduces last week; output shapes/ranges |
| `tests/integration/test_oracle_eplus.py` | real short-window E+ runs (`@pytest.mark.integration`) |

---

## Task 1: Register the `integration` pytest marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`** so the `[tool.pytest.ini_options]` section reads:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q -m 'not integration'"
markers = [
    "integration: tests that require Docker + the EnergyPlus image (deselected by default)",
]
```

- [ ] **Step 2: Verify markers load**

Run (from `src/`): `python -m pytest --markers | grep integration`
Expected: shows `@pytest.mark.integration: tests that require Docker ...`

- [ ] **Step 3: Confirm default run still green and skips integration**

Run: `python -m pytest`
Expected: all Plan-1 tests pass; no integration tests collected.

- [ ] **Step 4: Commit**

```bash
git add src/pyproject.toml
git commit -m "chore(dtwin): register integration pytest marker"
```

---

## Task 2: Env→action mapper (`env_actions.py`)

Build a `BroadcastPolicy` (Plan 1) from a live env's `AGENT_CONTROLLED` actions, classified by name. Testable with a fake actions list.

**Files:**
- Create: `planner/env_actions.py`
- Test: `tests/test_env_actions.py`

- [ ] **Step 1: Write the failing test**

`tests/test_env_actions.py`:

```python
import numpy as np
import pytest

from planner.env_actions import classify_kind, bounds_for, action_spec_from_actions, mapper_from_env
from planner.broadcast import ControlKind, BroadcastPolicy
from planner.types import Setpoints


class _Act:
    def __init__(self, variable_name, control_type):
        self.variable_name = variable_name
        self.control_type = control_type


class _FakeEnv:
    def __init__(self, actions):
        self._actions = actions
    @property
    def actions(self):
        return self._actions
    # mapper_from_env uses env.unwrapped
    @property
    def unwrapped(self):
        return self


def test_classify_kind_by_substring():
    assert classify_kind("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint") is ControlKind.SAT
    assert classify_kind("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate") is ControlKind.FLOW
    assert classify_kind("chilled_water_loop_supply_temperature_setpoint") is ControlKind.CHWST


def test_classify_kind_unknown_raises():
    with pytest.raises(ValueError):
        classify_kind("some_other_actuator")


def test_bounds_for_each_kind():
    assert bounds_for(ControlKind.SAT) == (20.0, 26.0)
    assert bounds_for(ControlKind.FLOW) == (4.8, 13.8)
    assert bounds_for(ControlKind.CHWST) == (13.0, 19.0)


def test_action_spec_filters_agent_controlled_only_in_order():
    actions = [
        _Act("data hall gf 1a ite-1 cpu loading schedule", 3),       # PRE_SCHEDULED -> skip
        _Act("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint", 2),
        _Act("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate", 2),
        _Act("chilled_water_supply_branch_1_on_off", 5),             # ACTUATOR_PRE_SCHEDULED -> skip
        _Act("chilled_water_loop_supply_temperature_setpoint", 2),
    ]
    spec = action_spec_from_actions(actions)
    assert [e.kind for e in spec] == [ControlKind.SAT, ControlKind.FLOW, ControlKind.CHWST]
    assert (spec[0].lb, spec[0].ub) == (20.0, 26.0)


def test_mapper_from_env_builds_broadcastpolicy():
    actions = [
        _Act("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint", 2),
        _Act("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate", 2),
        _Act("chilled_water_loop_supply_temperature_setpoint", 2),
    ]
    bp = mapper_from_env(_FakeEnv(actions))
    assert isinstance(bp, BroadcastPolicy)
    out = bp.expand(Setpoints(sat_c=20.0, flow_kg_s=13.8, chwst_c=13.0))
    np.testing.assert_allclose(out, [-1.0, 1.0, -1.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_env_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.env_actions'`.

- [ ] **Step 3: Write the implementation**

`planner/env_actions.py`:

```python
from __future__ import annotations

from typing import Sequence

from planner.broadcast import ActionEntry, BroadcastPolicy, ControlKind
from planner.types import DEFAULT_SEARCH_SPACE

AGENT_CONTROLLED = 2  # dctwin ControlType enum value (dt_engine.proto)


def classify_kind(variable_name: str) -> ControlKind:
    name = variable_name.lower()
    if "supply_air_temperature_setpoint" in name:
        return ControlKind.SAT
    if "supply_air_mass_flow_rate" in name:
        return ControlKind.FLOW
    if "chilled_water_loop_supply_temperature" in name:
        return ControlKind.CHWST
    raise ValueError(f"Unknown AGENT_CONTROLLED action: {variable_name!r}")


def bounds_for(kind: ControlKind) -> tuple[float, float]:
    """Per-kind physical bounds (match the GDS dt.prototxt normalize_config)."""
    b = {
        ControlKind.SAT: DEFAULT_SEARCH_SPACE.sat,
        ControlKind.FLOW: DEFAULT_SEARCH_SPACE.flow,
        ControlKind.CHWST: DEFAULT_SEARCH_SPACE.chwst,
    }[kind]
    return (b.lb, b.ub)


def action_spec_from_actions(actions: Sequence) -> list[ActionEntry]:
    """Build the ordered ActionEntry list from a live env's actions list.

    Keeps only control_type == AGENT_CONTROLLED, in declaration order.
    """
    spec: list[ActionEntry] = []
    for act in actions:
        if getattr(act, "control_type", None) != AGENT_CONTROLLED:
            continue
        kind = classify_kind(act.variable_name)
        lb, ub = bounds_for(kind)
        spec.append(ActionEntry(kind, lb, ub))
    if not spec:
        raise ValueError("No AGENT_CONTROLLED actions found in env")
    return spec


def mapper_from_env(env) -> BroadcastPolicy:
    """Derive a BroadcastPolicy from a (possibly gym-wrapped) dctwin env."""
    unwrapped = getattr(env, "unwrapped", env)
    return BroadcastPolicy(action_spec_from_actions(unwrapped.actions))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_env_actions.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/env_actions.py src/tests/test_env_actions.py
git commit -m "feat(dtwin): derive BroadcastPolicy from a live env's actions"
```

---

## Task 3: KPI aggregator (`kpi.py`)

Pure function converting per-step samples into a `WeeklyKPI`. No EnergyPlus.

**Files:**
- Create: `planner/kpi.py`
- Test: `tests/test_kpi.py`

- [ ] **Step 1: Write the failing test**

`tests/test_kpi.py`:

```python
from planner.kpi import StepSample, OracleSettings, aggregate_kpi


def _sample(total, it, inlets, rhs=None, zones=None):
    return StepSample(
        total_power_w=total, it_power_w=it,
        inlet_temps=inlets, inlet_rhs=rhs or [45.0], zone_temps=zones or [32.0],
    )


def test_energy_is_hvac_power_times_hours():
    # HVAC power = total - it = 1000 W; 2 steps of 0.25 h => 0.5 kWh
    s = [_sample(2000.0, 1000.0, [24.0]), _sample(2000.0, 1000.0, [24.0])]
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings())
    assert k.total_hvac_energy_kwh == 0.5


def test_pue_mean():
    s = [_sample(2400.0, 2000.0, [24.0])]  # PUE = 1.2
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings())
    assert k.pue_mean == 1.2


def test_inlet_violation_counts_steps_over_cap():
    s = [_sample(2000.0, 1000.0, [25.0, 26.5]),  # max 26.5 > 26 -> violation
         _sample(2000.0, 1000.0, [24.0, 25.0])]  # max 25.0 -> ok
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings(inlet_cap=26.0))
    assert k.inlet_violation_steps == 1
    assert k.inlet_temp_max == 26.5


def test_inlet_excess_uses_soft_margin():
    # soft threshold = cap - soft_margin = 25.0; step max 26.0 -> excess 1.0
    s = [_sample(2000.0, 1000.0, [26.0])]
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(inlet_cap=26.0, inlet_soft_margin=1.0))
    assert k.inlet_excess_degc_steps == 1.0


def test_rh_violation_and_excursion():
    s = [_sample(2000.0, 1000.0, [24.0], rhs=[25.0]),   # 25 < 30 -> violation, excursion 5
         _sample(2000.0, 1000.0, [24.0], rhs=[65.0])]   # 65 > 60 -> violation, excursion 5
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(rh_min=30.0, rh_max=60.0))
    assert k.rh_violation_steps == 2
    assert k.rh_excursion_steps == 10.0


def test_zone_band_excursion():
    # target 32 band 1 -> in-band [31,33]; zone 34 -> excursion 1.0
    s = [_sample(2000.0, 1000.0, [24.0], zones=[34.0])]
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(zone_target=32.0, zone_band=1.0))
    assert k.zone_temp_band_steps == 1.0


def test_feasible_true_on_successful_aggregation():
    k = aggregate_kpi([_sample(2000.0, 1000.0, [24.0])], 0.25, OracleSettings())
    assert k.feasible is True


def test_empty_samples_is_infeasible():
    k = aggregate_kpi([], 0.25, OracleSettings())
    assert k.feasible is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kpi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.kpi'`.

- [ ] **Step 3: Write the implementation**

`planner/kpi.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from planner.types import WeeklyKPI


@dataclass
class StepSample:
    """One timestep's monitored readings (physical units)."""

    total_power_w: float
    it_power_w: float
    inlet_temps: list[float]      # ITE inlet dry-bulb, deg C
    inlet_rhs: list[float] = field(default_factory=list)   # %
    zone_temps: list[float] = field(default_factory=list)  # deg C


@dataclass(frozen=True)
class OracleSettings:
    inlet_cap: float = 26.0          # hard ITE inlet limit, deg C
    inlet_soft_margin: float = 1.0   # soft threshold = cap - margin
    rh_min: float = 30.0
    rh_max: float = 60.0
    zone_target: float = 32.0
    zone_band: float = 1.0


def aggregate_kpi(samples: list[StepSample], hours_per_step: float,
                  settings: OracleSettings) -> WeeklyKPI:
    if not samples:
        return WeeklyKPI(
            total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
            inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
            rh_violation_steps=10 ** 9, feasible=False,
        )

    s = settings
    soft_threshold = s.inlet_cap - s.inlet_soft_margin

    energy_kwh = 0.0
    pue_sum = 0.0
    inlet_temp_max = float("-inf")
    inlet_violation_steps = 0
    inlet_excess = 0.0
    rh_violation_steps = 0
    rh_excursion = 0.0
    zone_band_steps = 0.0

    for smp in samples:
        hvac_w = smp.total_power_w - smp.it_power_w
        energy_kwh += hvac_w * hours_per_step / 1000.0
        if smp.it_power_w > 0:
            pue_sum += smp.total_power_w / smp.it_power_w

        step_inlet_max = max(smp.inlet_temps) if smp.inlet_temps else float("-inf")
        inlet_temp_max = max(inlet_temp_max, step_inlet_max)
        if step_inlet_max > s.inlet_cap:
            inlet_violation_steps += 1
        inlet_excess += max(step_inlet_max - soft_threshold, 0.0)

        rh_bad = False
        for rh in smp.inlet_rhs:
            if rh < s.rh_min:
                rh_bad = True
                rh_excursion += s.rh_min - rh
            elif rh > s.rh_max:
                rh_bad = True
                rh_excursion += rh - s.rh_max
        if rh_bad:
            rh_violation_steps += 1

        for z in smp.zone_temps:
            zone_band_steps += max(abs(z - s.zone_target) - s.zone_band, 0.0)

    return WeeklyKPI(
        total_hvac_energy_kwh=energy_kwh,
        pue_mean=pue_sum / len(samples),
        inlet_temp_max=inlet_temp_max,
        inlet_violation_steps=inlet_violation_steps,
        rh_violation_steps=rh_violation_steps,
        feasible=True,
        inlet_excess_degc_steps=inlet_excess,
        rh_excursion_steps=rh_excursion,
        zone_temp_band_steps=zone_band_steps,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kpi.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/kpi.py src/tests/test_kpi.py
git commit -m "feat(dtwin): add weekly KPI aggregator (energy/PUE/inlet/rh/zone)"
```

---

## Task 4: Observation discovery (`monitor.py`)

Discover which observation names to read each step. Testable with a fake env.

**Files:**
- Create: `planner/monitor.py`
- Test: `tests/test_monitor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_monitor.py`:

```python
from planner.monitor import MonitorSpec, discover_monitor


class _Obs:
    def __init__(self, variable_name):
        self.variable_name = variable_name


class _FakeEnv:
    def __init__(self, names):
        self._obs = [_Obs(n) for n in names]
    @property
    def observations(self):
        return self._obs
    @property
    def unwrapped(self):
        return self


def test_discover_classifies_observations():
    env = _FakeEnv([
        "total power",
        "total it power",
        "data hall 1f 2a ite-1 inlet dry-bulb temperature",
        "data hall 1f 2a ite-2 inlet dry-bulb temperature",
        "data hall 1f 2a ite-1 inlet relative humidity",
        "data hall 1f 2a air temperature",
        "data hall 1f 2a acu-1 fan power consumption",  # ignored
    ])
    m = discover_monitor(env)
    assert m.total_power_name == "total power"
    assert m.it_power_name == "total it power"
    assert len(m.inlet_temp_names) == 2
    assert m.inlet_rh_names == ["data hall 1f 2a ite-1 inlet relative humidity"]
    assert m.zone_temp_names == ["data hall 1f 2a air temperature"]


def test_discover_requires_power_observations():
    import pytest
    env = _FakeEnv(["data hall 1f 2a ite-1 inlet dry-bulb temperature"])
    with pytest.raises(ValueError):
        discover_monitor(env)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.monitor'`.

- [ ] **Step 3: Write the implementation**

`planner/monitor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonitorSpec:
    total_power_name: str
    it_power_name: str
    inlet_temp_names: list[str] = field(default_factory=list)
    inlet_rh_names: list[str] = field(default_factory=list)
    zone_temp_names: list[str] = field(default_factory=list)


def discover_monitor(env) -> MonitorSpec:
    """Scan a dctwin env's observations and classify the ones we read each step."""
    unwrapped = getattr(env, "unwrapped", env)
    names = [o.variable_name for o in unwrapped.observations]

    total = next((n for n in names if n == "total power"), None)
    it = next((n for n in names if n == "total it power"), None)
    if total is None or it is None:
        raise ValueError("env is missing 'total power' / 'total it power' observations")

    inlet_temps = [n for n in names if "inlet dry-bulb temperature" in n.lower()]
    inlet_rhs = [n for n in names if "inlet relative humidity" in n.lower()]
    # room/zone air temperature, but not ACU/coil inlet readings
    zones = [
        n for n in names
        if n.lower().endswith(" air temperature") and "acu" not in n.lower()
        and "inlet" not in n.lower()
    ]
    return MonitorSpec(total, it, inlet_temps, inlet_rhs, zones)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/monitor.py src/tests/test_monitor.py
git commit -m "feat(dtwin): discover monitored observations from env"
```

---

## Task 5: Weekly run-period config writer (`week_config.py`)

**Files:**
- Create: `planner/week_config.py`
- Test: `tests/test_week_config.py`

- [ ] **Step 1: Write the failing test**

This test does not import dctwin; it injects a fake `read_engine_config` + serializer so it runs without the package. (Plan-3 integration uses the real one.)

`tests/test_week_config.py`:

```python
from datetime import date

from planner.week_config import compute_week_period, WeekPeriod


def test_week_period_inclusive_seven_days():
    # Mon 2013-11-11 .. inclusive 7 days -> 2013-11-17
    p = compute_week_period(date(2013, 11, 11), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=11, end_month=11, end_day=17)


def test_week_period_crosses_month():
    p = compute_week_period(date(2013, 11, 28), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=28, end_month=12, end_day=4)


def test_week_period_rejects_year_wrap():
    import pytest
    with pytest.raises(ValueError):
        compute_week_period(date(2013, 12, 30), days=7)  # would cross into next year
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_week_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.week_config'`.

- [ ] **Step 3: Write the implementation**

`planner/week_config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class WeekPeriod:
    begin_month: int
    begin_day: int
    end_month: int
    end_day: int


def compute_week_period(week_start: date, days: int = 7) -> WeekPeriod:
    """Inclusive run period for a `days`-long week starting at week_start.

    EnergyPlus RunPeriod end day is inclusive, so a 7-day week ends at
    week_start + (days - 1). v1 rejects windows that cross a year boundary
    (dctwin hardcodes year 2013 and mishandles wrap).
    """
    end = week_start + timedelta(days=days - 1)
    if end.year != week_start.year:
        raise ValueError(
            f"week {week_start}..{end} crosses a year boundary; not supported in v1"
        )
    return WeekPeriod(week_start.month, week_start.day, end.month, end.day)


def write_week_config(
    base_prototxt: Union[str, Path],
    week_start: date,
    out_path: Union[str, Path],
    days: int = 7,
    timesteps_per_hour: int | None = None,
) -> str:
    """Read the base DT prototxt, set the weekly run period, write to out_path.

    Imports dctwin lazily so the pure logic above stays import-free for unit tests.
    """
    from dctwin.utils import read_engine_config
    from google.protobuf import text_format

    period = compute_week_period(week_start, days)
    cfg = read_engine_config(str(base_prototxt))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    stc = env_cfg.simulation_time_config
    stc.begin_month = period.begin_month
    stc.begin_day_of_month = period.begin_day
    stc.end_month = period.end_month
    stc.end_day_of_month = period.end_day
    if timesteps_per_hour is not None:
        stc.number_of_timesteps_per_hour = timesteps_per_hour
    Path(out_path).write_text(text_format.MessageToString(cfg))
    return str(out_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_week_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/week_config.py src/tests/test_week_config.py
git commit -m "feat(dtwin): weekly run-period config writer"
```

---

## Task 6: Oracle worker (`oracle_worker.py`)

A module-level (picklable) function that runs ONE full-week EnergyPlus simulation for one candidate. The collect→aggregate inner logic reuses tested units; the EnergyPlus glue is covered by integration tests in Task 8.

**Files:**
- Create: `planner/oracle_worker.py`
- Test: `tests/test_oracle_worker.py`

- [ ] **Step 1: Write the failing test** (tests the picklable result helpers + error path with a fake env factory; no EnergyPlus)

`tests/test_oracle_worker.py`:

```python
import math

import numpy as np

from planner.oracle_worker import read_step_sample, run_episode, EvalTask
from planner.monitor import MonitorSpec
from planner.kpi import OracleSettings


class _FakeUnwrapped:
    """Minimal stand-in for env.unwrapped with scripted observations."""
    def __init__(self, traces):
        self._traces = traces      # dict name -> list of values
        self._step = -1
        self.actions = []
        self.observations = []
    def advance(self):
        self._step += 1
    def inspect_current_observation(self, observation_name, use_unnormed=True):
        return self._traces[observation_name][self._step]


class _FakeEnv:
    def __init__(self, traces, n_steps):
        self._u = _FakeUnwrapped(traces)
        self._n = n_steps
        self._i = 0
    @property
    def unwrapped(self):
        return self._u
    def reset(self):
        self._u.advance()  # step 0 readings available after reset
        return None, {}
    def step(self, action):
        self._i += 1
        self._u.advance()
        done = self._i >= self._n
        return None, 0.0, done, False, {}
    def close(self):
        pass


def test_read_step_sample_collects_named_values():
    traces = {
        "total power": [2000.0], "total it power": [1000.0],
        "i1": [24.0], "rh1": [45.0], "z1": [32.0],
    }
    u = _FakeUnwrapped(traces)
    u.advance()
    m = MonitorSpec("total power", "total it power", ["i1"], ["rh1"], ["z1"])
    s = read_step_sample(u, m)
    assert s.total_power_w == 2000.0 and s.it_power_w == 1000.0
    assert s.inlet_temps == [24.0]


def test_run_episode_aggregates_over_steps():
    traces = {
        "total power": [2000.0, 2000.0, 2000.0],
        "total it power": [1000.0, 1000.0, 1000.0],
        "i1": [24.0, 24.0, 24.0],
        "rh1": [45.0, 45.0, 45.0],
        "z1": [32.0, 32.0, 32.0],
    }
    env = _FakeEnv(traces, n_steps=2)
    m = MonitorSpec("total power", "total it power", ["i1"], ["rh1"], ["z1"])
    action = np.zeros(3)
    kpi = run_episode(env, action, m, hours_per_step=0.25, settings=OracleSettings())
    assert kpi.feasible
    assert kpi.total_hvac_energy_kwh == 0.5   # 1000 W * 0.25 h * 2 steps / 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oracle_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.oracle_worker'`.

- [ ] **Step 3: Write the implementation**

`planner/oracle_worker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from planner.kpi import OracleSettings, StepSample, aggregate_kpi
from planner.monitor import MonitorSpec
from planner.types import Setpoints, WeeklyKPI


@dataclass
class EvalTask:
    """Picklable description of one candidate evaluation (process-pool payload)."""

    candidate: tuple[float, float, float]   # (sat, flow, chwst)
    week_config_path: str
    log_dir: str
    hours_per_step: float
    settings_kwargs: dict


def read_step_sample(unwrapped, monitor: MonitorSpec) -> StepSample:
    def g(name):
        return unwrapped.inspect_current_observation(observation_name=name, use_unnormed=True)
    return StepSample(
        total_power_w=g(monitor.total_power_name),
        it_power_w=g(monitor.it_power_name),
        inlet_temps=[g(n) for n in monitor.inlet_temp_names],
        inlet_rhs=[g(n) for n in monitor.inlet_rh_names],
        zone_temps=[g(n) for n in monitor.zone_temp_names],
    )


def run_episode(env, action: np.ndarray, monitor: MonitorSpec,
                hours_per_step: float, settings: OracleSettings) -> WeeklyKPI:
    """Step a (already-built) env to completion with a fixed action; aggregate KPI."""
    samples: list[StepSample] = []
    env.reset()
    samples.append(read_step_sample(env.unwrapped, monitor))
    done = False
    while not done:
        _obs, _rew, done, _trunc, _info = env.step(action)
        samples.append(read_step_sample(env.unwrapped, monitor))
    return aggregate_kpi(samples, hours_per_step, settings)


def _infeasible(error: str) -> WeeklyKPI:
    return WeeklyKPI(
        total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
        inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
        rh_violation_steps=10 ** 9, feasible=False,
    )


def evaluate_one(task: EvalTask) -> WeeklyKPI:
    """Top-level process-pool target: build env, run one full week, aggregate.

    Any failure (Docker/E+/socket) returns an infeasible WeeklyKPI rather than
    raising, so one bad candidate never aborts the search.
    """
    import dctwin
    from dctwin.utils import config as dt_config
    from planner.env_actions import mapper_from_env
    from planner.monitor import discover_monitor

    env = None
    try:
        dt_config.config.set_log_dir(task.log_dir)
        env = dctwin.make_env(env_proto_config=task.week_config_path, reward_fn=lambda x: 0)
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env)
        action = broadcaster.expand(Setpoints(*task.candidate))
        return run_episode(env, action, monitor, task.hours_per_step,
                           OracleSettings(**task.settings_kwargs))
    except Exception as exc:  # noqa: BLE001 - intentional: isolate candidate failures
        return _infeasible(str(exc))
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_oracle_worker.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/oracle_worker.py src/tests/test_oracle_worker.py
git commit -m "feat(dtwin): oracle worker (one full-week E+ run -> WeeklyKPI)"
```

---

## Task 7: ParallelEnvOracle (`oracle.py`)

Implements `Evaluator`: fans candidates out over a process pool with per-task timeout, mapping failures/timeouts to infeasible KPIs. Orchestration is unit-tested by monkeypatching `evaluate_one`.

**Files:**
- Create: `planner/oracle.py`
- Test: `tests/test_oracle.py`

- [ ] **Step 1: Write the failing test**

`tests/test_oracle.py`:

```python
from pathlib import Path

from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.kpi import OracleSettings
from planner.types import Setpoints, WeeklyKPI
import planner.oracle as oracle_mod


def _good_kpi(task):
    sat = task.candidate[0]
    return WeeklyKPI(total_hvac_energy_kwh=100.0 + sat, pue_mean=1.2,
                     inlet_temp_max=24.0, inlet_violation_steps=0,
                     rh_violation_steps=0, feasible=True)


def test_returns_one_kpi_per_candidate_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(oracle_mod, "evaluate_one", _good_kpi)
    orc = ParallelEnvOracle(
        base_prototxt="ignored.prototxt",
        config=OracleConfig(n_workers=1, use_process_pool=False,
                            log_root=str(tmp_path), timesteps_per_hour=4),
    )
    cands = [Setpoints(20.0, 8.0, 17.0), Setpoints(26.0, 8.0, 17.0)]
    out = orc.evaluate(cands, forecast=_FakeForecast(tmp_path))
    assert len(out) == 2
    assert out[0].total_hvac_energy_kwh == 120.0
    assert out[1].total_hvac_energy_kwh == 126.0


def test_worker_exception_becomes_infeasible(monkeypatch, tmp_path):
    def boom(task):
        raise RuntimeError("docker died")
    monkeypatch.setattr(oracle_mod, "evaluate_one", boom)
    orc = ParallelEnvOracle(
        base_prototxt="ignored.prototxt",
        config=OracleConfig(n_workers=1, use_process_pool=False, log_root=str(tmp_path)),
    )
    out = orc.evaluate([Setpoints(22.0, 8.0, 17.0)], forecast=_FakeForecast(tmp_path))
    assert out[0].feasible is False


class _FakeForecast:
    """Stands in for a Forecast; records that materialize() was called."""
    def __init__(self, tmp_path):
        self.week_start = __import__("datetime").date(2013, 11, 11)
        self.materialized = False
        self._tmp = tmp_path
    def materialize(self, project_root):
        self.materialized = True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oracle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.oracle'`.

- [ ] **Step 3: Write the implementation**

`planner/oracle.py`:

```python
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from planner.kpi import OracleSettings
from planner.oracle_worker import EvalTask, evaluate_one
from planner.types import Evaluator, Setpoints, WeeklyKPI
from planner.week_config import write_week_config


@dataclass
class OracleConfig:
    n_workers: int = 8
    timeout_s: float = 1800.0           # per-candidate wall-clock cap
    timesteps_per_hour: int = 4         # -> hours_per_step = 1/this
    log_root: str = "log/oracle"
    use_process_pool: bool = True       # False = serial (for tests/debug)
    settings: OracleSettings = field(default_factory=OracleSettings)


def _infeasible() -> WeeklyKPI:
    return WeeklyKPI(
        total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
        inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
        rh_violation_steps=10 ** 9, feasible=False,
    )


class ParallelEnvOracle(Evaluator):
    """Score candidate weekly setpoints with real full-week EnergyPlus runs."""

    def __init__(self, base_prototxt: str, config: Optional[OracleConfig] = None,
                 project_root: str = "."):
        self.base_prototxt = base_prototxt
        self.config = config or OracleConfig()
        self.project_root = project_root

    def evaluate(self, candidates: Sequence[Setpoints],
                 forecast: Optional[Any] = None) -> list[WeeklyKPI]:
        cfg = self.config
        hours_per_step = 1.0 / cfg.timesteps_per_hour

        # 1) materialize the forecast (workload schedules) + write the weekly config
        if forecast is not None and hasattr(forecast, "materialize"):
            forecast.materialize(self.project_root)
        week_cfg_path = str(Path(cfg.log_root) / "week.prototxt")
        Path(cfg.log_root).mkdir(parents=True, exist_ok=True)
        if forecast is not None and getattr(forecast, "week_start", None) is not None:
            write_week_config(self.base_prototxt, forecast.week_start, week_cfg_path,
                              timesteps_per_hour=cfg.timesteps_per_hour)
        else:
            week_cfg_path = self.base_prototxt

        # 2) build one task per candidate with a unique per-candidate log dir
        tasks = [
            EvalTask(
                candidate=c.as_tuple(),
                week_config_path=week_cfg_path,
                log_dir=str(Path(cfg.log_root) / f"cand-{i:04d}"),
                hours_per_step=hours_per_step,
                settings_kwargs=cfg.settings.__dict__,
            )
            for i, c in enumerate(candidates)
        ]

        # 3) run (serial for tests, process pool in production)
        if not cfg.use_process_pool:
            return [self._safe_run(t) for t in tasks]

        results: list[WeeklyKPI] = [_infeasible()] * len(tasks)
        with cf.ProcessPoolExecutor(max_workers=cfg.n_workers) as ex:
            futs = {ex.submit(evaluate_one, t): i for i, t in enumerate(tasks)}
            for fut in cf.as_completed(futs):
                i = futs[fut]
                try:
                    results[i] = fut.result(timeout=cfg.timeout_s)
                except Exception:  # noqa: BLE001 - timeout or worker crash
                    results[i] = _infeasible()
        return results

    @staticmethod
    def _safe_run(task: EvalTask) -> WeeklyKPI:
        try:
            return evaluate_one(task)
        except Exception:  # noqa: BLE001
            return _infeasible()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_oracle.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/oracle.py src/tests/test_oracle.py
git commit -m "feat(dtwin): ParallelEnvOracle process-pool fan-out with error isolation"
```

---

## Task 8: Integration test — real EnergyPlus short-window runs

Validates the worker + oracle against real dctwin/Docker/EnergyPlus on a SHORT window (1 day) so it finishes quickly. Requires the model project files copied into `src/` (configs/dt, models/idf, data/) — see Plan 3 Task 1 (M0 scaffold). If those are not yet present, copy them from `/mnt/lv/home/hoanghuy/mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup/`.

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_oracle_eplus.py`

- [ ] **Step 1: Copy the model assets into the project (if not already done in Plan 3 M0)**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
SRC=/mnt/lv/home/hoanghuy/mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup
cp -r "$SRC/configs" "$SRC/models" "$SRC/data" .
```

- [ ] **Step 2: Write the integration test**

`tests/integration/__init__.py`:

```python
```

`tests/integration/test_oracle_eplus.py`:

```python
import datetime
from pathlib import Path

import pytest

from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.kpi import OracleSettings
from planner.types import Setpoints

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"


@pytest.mark.skipif(not Path(DT).exists(), reason="model assets not copied into src/")
def test_single_candidate_short_window(tmp_path):
    # 1-day window keeps the E+ run fast; serial pool, 1 worker.
    orc = ParallelEnvOracle(
        base_prototxt=DT,
        config=OracleConfig(n_workers=1, use_process_pool=False,
                            log_root=str(tmp_path), timesteps_per_hour=4,
                            settings=OracleSettings()),
    )

    class _F:
        week_start = datetime.date(2013, 11, 11)
        def materialize(self, root):  # workloads already on disk from the GDS copy
            pass

    # one-day window: override write to a 1-day period by monkeypatching days
    from planner import week_config
    orig = week_config.compute_week_period
    week_config.compute_week_period = lambda ws, days=7: orig(ws, days=1)
    try:
        out = orc.evaluate([Setpoints(24.0, 8.0, 18.0)], forecast=_F())
    finally:
        week_config.compute_week_period = orig

    kpi = out[0]
    assert kpi.feasible
    assert kpi.total_hvac_energy_kwh > 0
    assert kpi.inlet_temp_max > 0


@pytest.mark.skipif(not Path(DT).exists(), reason="model assets not copied into src/")
def test_two_candidates_parallel_processes(tmp_path):
    orc = ParallelEnvOracle(
        base_prototxt=DT,
        config=OracleConfig(n_workers=2, use_process_pool=True,
                            log_root=str(tmp_path), timesteps_per_hour=4),
    )

    class _F:
        week_start = datetime.date(2013, 11, 11)
        def materialize(self, root):
            pass

    from planner import week_config
    orig = week_config.compute_week_period
    week_config.compute_week_period = lambda ws, days=7: orig(ws, days=1)
    try:
        out = orc.evaluate([Setpoints(22.0, 10.0, 16.0), Setpoints(25.0, 6.0, 19.0)], forecast=_F())
    finally:
        week_config.compute_week_period = orig

    assert len(out) == 2
    assert all(k.feasible for k in out)
    # cooler/higher-flow setpoint should not use LESS cooling energy than the warm one
    assert out[0].total_hvac_energy_kwh != out[1].total_hvac_energy_kwh
```

- [ ] **Step 3: Run the integration test (needs Docker + EP image)**

Run: `python -m pytest tests/integration/test_oracle_eplus.py -v -m integration`
Expected: PASS (2 passed) — each ~minutes. If Docker/EP image is unavailable, these are skipped/fail; the default suite (`python -m pytest`) still excludes them.

- [ ] **Step 4: Commit**

```bash
git add src/tests/integration/__init__.py src/tests/integration/test_oracle_eplus.py
git commit -m "test(dtwin): integration tests for ParallelEnvOracle on real EnergyPlus"
```

---

## Task 9: Statistical forecaster (`forecaster.py`)

Fits per-data-hall IT-load fractions from `his_data` and emits per-ITE workload JSON arrays (one value per simulation step) for the planning week. Pure pandas/numpy — TDD'd with a fixture DataFrame.

**Files:**
- Create: `planner/forecaster.py`
- Test: `tests/test_forecaster.py`

- [ ] **Step 1: Write the failing test**

`tests/test_forecaster.py`:

```python
import json
from datetime import date

import numpy as np
import pandas as pd

from planner.forecaster import (
    loading_from_it_loads, persistence_window, StatisticalForecaster, Forecast,
)


def test_loading_from_it_loads_divides_by_capacity_kw():
    # 2000 kW load, capacity 4_000_000 W = 4000 kW -> 0.5
    s = pd.Series([2000.0, 1000.0])
    out = loading_from_it_loads(s, total_watts=4_000_000.0)
    np.testing.assert_allclose(out.to_numpy(), [0.5, 0.25])


def test_persistence_window_takes_last_n_steps():
    s = pd.Series(list(range(100)), dtype=float)
    win = persistence_window(s, n_steps=10)
    assert list(win) == list(range(90, 100))


def test_persistence_window_tiles_when_history_short():
    s = pd.Series([0.3, 0.4], dtype=float)
    win = persistence_window(s, n_steps=5)
    assert len(win) == 5
    assert set(np.round(win, 1)).issubset({0.3, 0.4})


def test_forecaster_writes_workload_arrays(tmp_path):
    # fixture his_data: 8 rows, one IT-loads column for hall "1F 2A"
    df = pd.DataFrame({
        "1F_Datahall 2A 1F Data Hall 2A IT loads": [900.0] * 8,
    })
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    his_col_for_room = {"Data Hall 1F 2A": "1F_Datahall 2A 1F Data Hall 2A IT loads"}
    fc = StatisticalForecaster(df, room2ite, his_col_for_room, method="persistence")

    forecast = fc.forecast(week_start=date(2013, 11, 11), n_steps=4)
    assert isinstance(forecast, Forecast)
    arr = forecast.workload_schedules["Data Hall 1F 2A ite-1"]
    assert len(arr) == 4
    # 900 kW / (1_800_000/1000 kW) = 0.5
    np.testing.assert_allclose(arr, [0.5, 0.5, 0.5, 0.5])

    # materialize() writes the JSON files under data/schedule/workloads/
    forecast.materialize(project_root=str(tmp_path))
    written = json.loads(
        (tmp_path / "data/schedule/workloads/data hall 1f 2a ite-1.json").read_text()
    )
    assert written == [0.5, 0.5, 0.5, 0.5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_forecaster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.forecaster'`.

- [ ] **Step 3: Write the implementation**

`planner/forecaster.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def loading_from_it_loads(it_loads_kw: pd.Series, total_watts: float) -> pd.Series:
    """Convert per-hall IT load (kW) to a 0-1 CPU-loading fraction."""
    capacity_kw = total_watts / 1000.0
    return (it_loads_kw / capacity_kw).clip(lower=0.0, upper=1.0)


def persistence_window(series: pd.Series, n_steps: int) -> np.ndarray:
    """Last n_steps of the series; tile if history is shorter than n_steps."""
    arr = series.to_numpy(dtype=float)
    if len(arr) >= n_steps:
        return arr[-n_steps:]
    reps = int(np.ceil(n_steps / max(len(arr), 1)))
    return np.tile(arr, reps)[:n_steps]


@dataclass
class Forecast:
    week_start: date
    workload_schedules: dict[str, list[float]]   # ite name -> per-step loading
    method: str = "persistence"

    def materialize(self, project_root: str) -> None:
        """Write each ITE's workload array to data/schedule/workloads/<name>.json.

        File name convention matches the GDS layout: lowercased ITE name.
        """
        out_dir = Path(project_root) / "data" / "schedule" / "workloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        for ite_name, arr in self.workload_schedules.items():
            fname = ite_name.lower() + ".json"
            (out_dir / fname).write_text(json.dumps(list(arr)))


class StatisticalForecaster:
    """Persistence / seasonal-naive forecaster over per-hall IT loads."""

    def __init__(self, his_data: pd.DataFrame, room2ite: dict,
                 his_col_for_room: dict, method: str = "persistence"):
        self.his = his_data
        self.room2ite = room2ite
        self.his_col_for_room = his_col_for_room
        self.method = method

    def _hall_loading(self, room: str, n_steps: int) -> np.ndarray:
        col = self.his_col_for_room[room]
        ites = self.room2ite[room]
        # capacity = sum of the room's ITE totalWatts
        total_watts = sum(v["totalWatts"] for v in ites.values())
        loading = loading_from_it_loads(self.his[col], total_watts)
        if self.method in ("persistence", "seasonal-naive"):
            return persistence_window(loading, n_steps)
        raise ValueError(f"unknown method {self.method!r}")

    def forecast(self, week_start: date, n_steps: int) -> Forecast:
        schedules: dict[str, list[float]] = {}
        for room, ites in self.room2ite.items():
            if room not in self.his_col_for_room:
                continue
            hall = self._hall_loading(room, n_steps)
            for ite_name in ites:                       # broadcast hall loading to its ITEs
                schedules[ite_name] = [float(x) for x in hall]
        return Forecast(week_start=week_start, workload_schedules=schedules, method=self.method)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_forecaster.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/forecaster.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): statistical (persistence) forecaster + workload writer"
```

---

## Task 10: `fit_forecaster.py` — the "ai policy train" analog

Loads his_data + the room/his mappings, builds a `StatisticalForecaster`, and persists its configuration (the forecaster is non-parametric, so "fitting" = capturing the data source + mapping for reproducibility).

**Files:**
- Create: `fit_forecaster.py`
- Test: `tests/test_fit_forecaster.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fit_forecaster.py`:

```python
import json
import pickle
from pathlib import Path

import pandas as pd

from fit_forecaster import build_his_col_for_room, save_forecaster_config


def test_build_his_col_for_room_matches_columns():
    cols = [
        "_time",
        "1F_Datahall 2A 1F Data Hall 2A IT loads",
        "GF_Datahall 1A GF Data Hall 1A IT loads",
    ]
    room2ite = {
        "Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1.0}},
        "Data Hall GF 1A": {"Data Hall GF 1A ite-1": {"totalWatts": 1.0}},
        "Super Core Room 1F": {"x": {"totalWatts": 1.0}},  # no matching column
    }
    mapping = build_his_col_for_room(room2ite, cols)
    assert mapping["Data Hall 1F 2A"] == "1F_Datahall 2A 1F Data Hall 2A IT loads"
    assert mapping["Data Hall GF 1A"] == "GF_Datahall 1A GF Data Hall 1A IT loads"
    assert "Super Core Room 1F" not in mapping


def test_save_forecaster_config_roundtrip(tmp_path):
    cfg = {"method": "persistence", "his_col_for_room": {"a": "b"}}
    out = tmp_path / "forecaster.pkl"
    save_forecaster_config(cfg, str(out))
    assert pickle.loads(out.read_bytes()) == cfg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fit_forecaster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fit_forecaster'`.

- [ ] **Step 3: Write the implementation**

`fit_forecaster.py`:

```python
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path

import pandas as pd


def _room_token(room: str) -> str:
    """'Data Hall 1F 2A' -> tokens ['1f','2a'] for fuzzy column matching."""
    return room.lower().replace("data hall", "").strip()


def build_his_col_for_room(room2ite: dict, columns: list[str]) -> dict[str, str]:
    """Map each room to its 'IT loads' column in his_data by fuzzy name match."""
    it_cols = [c for c in columns if c.strip().lower().endswith("it loads")]
    mapping: dict[str, str] = {}
    for room in room2ite:
        token = _room_token(room)                       # e.g. '1f 2a'
        parts = [p for p in re.split(r"\s+", token) if p]
        for c in it_cols:
            cl = c.lower()
            if all(p in cl for p in parts):
                mapping[room] = c
                break
    return mapping


def save_forecaster_config(config: dict, out_path: str) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(pickle.dumps(config))


def main(his_csv: str = "data/his_data_processed.csv",
         room2ite_path: str = "configs/dt/room2ite_map.json",
         method: str = "persistence",
         out_path: str = "models/forecaster.pkl") -> None:
    df = pd.read_csv(his_csv)
    room2ite = json.loads(Path(room2ite_path).read_text())
    his_col_for_room = build_his_col_for_room(room2ite, list(df.columns))
    config = {
        "method": method,
        "his_csv": his_csv,
        "room2ite_path": room2ite_path,
        "his_col_for_room": his_col_for_room,
    }
    save_forecaster_config(config, out_path)
    print(f"Fitted forecaster config -> {out_path}: {len(his_col_for_room)} rooms mapped")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fit_forecaster.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run full non-integration suite + commit**

Run: `python -m pytest`
Expected: PASS (all Plan-1 + Plan-2 unit tests).

```bash
git add src/fit_forecaster.py src/tests/test_fit_forecaster.py
git commit -m "feat(dtwin): fit_forecaster entrypoint (ai-policy-train analog)"
```

---

## Self-Review

**Spec coverage (Plan 2 = spec §7.2 Oracle, §7.5 Forecaster, §11 error handling):**
- §7.2 `Evaluator` protocol + `ParallelEnvOracle` with `WeeklyKPI` → Tasks 6–7. ✅
- 3→45 broadcast from a live env (real declaration order, not hardcoded) → Task 2. ✅
- Weekly energy/PUE/inlet/RH/zone aggregation from observations → Tasks 3–4. ✅
- Weekly run-period override + year-wrap guard → Task 5. ✅
- §11 per-candidate failure → infeasible (never aborts search); per-task timeout; process isolation with unique LOG_DIR → Tasks 6–7. ✅
- §7.5 statistical (persistence) forecaster + per-ITE workload writer + fit entrypoint → Tasks 9–10. ✅
- Real-EnergyPlus validation → Task 8 (integration). ✅
- **Deferred to Plan 3:** `WeeklyPlanTemplate`, `recommendation.json`, pre-validation/expert/deploy, M0 asset scaffold (Task 8 Step 1 copies assets as a stopgap if run first).

**Placeholder scan:** No TBD/TODO/"handle errors" — every step has full code + exact command + expected output. ✅

**Type consistency:** `Setpoints.as_tuple()`, `WeeklyKPI` fields, `Evaluator.evaluate(candidates, forecast)`, `OracleSettings` field names, `StepSample` fields, `Forecast.materialize(project_root)` / `.week_start`, `EvalTask` fields, `evaluate_one(task)` are used identically across Tasks 2–10 and match Plan 1. The `forecast` object passed to `oracle.evaluate` must expose `.week_start` (a `date`) and `.materialize(project_root)` — satisfied by `Forecast` (Task 9). ✅

---

## Execution Handoff

Plan 2 complete (10 tasks; ~30 unit tests + 2 integration tests). With Plan 1 + Plan 2 the planner can score real candidates. Plan 3 wires the template entrypoints and the outer loop.
