import math

import numpy as np

from planner.oracle_worker import read_step_sample, run_episode, EvalTask
from planner.monitor import MonitorSpec
from planner.kpi import OracleSettings


class _FakeUnwrapped:
    """Minimal stand-in for env.unwrapped with scripted observations."""
    def __init__(self, traces):
        self._traces = traces
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
        self._u.advance()
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
    assert kpi.total_hvac_energy_kwh == 0.5


def test_run_episode_with_samples_returns_kpi_and_per_step():
    from planner.oracle_worker import run_episode_with_samples
    # reset sample (step 0) + 8 stepped samples -> indices 0..8 read, so 10 values is safe
    traces = {"total power": [1200.0] * 10, "total it power": [1000.0] * 10,
              "inlet_a": [24.0] * 10}
    env = _FakeEnv(traces, n_steps=9)
    mon = MonitorSpec(total_power_name="total power", it_power_name="total it power",
                      inlet_temp_names=["inlet_a"], inlet_rh_names=[], zone_temp_names=[])
    kpi, samples = run_episode_with_samples(env, np.zeros(3), mon,
                                            hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    assert kpi.feasible
    assert len(samples) == 9              # reset sample + 8 in-loop samples
    assert samples[0].inlet_temps == [24.0]


def test_teardown_container_is_best_effort():
    from planner.oracle_worker import _teardown_container
    calls = {"stopped": False}

    class _Container:
        def stop(self, timeout=5):
            calls["stopped"] = True
        def remove(self, force=True):
            raise RuntimeError("already gone")   # must be swallowed

    class _Backend:
        container = _Container()

    class _Env:
        class unwrapped:
            eplus_backend = _Backend()

    _teardown_container(_Env())          # must not raise
    assert calls["stopped"] is True


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


def test_run_with_timeout_returns_value_on_fast_run():
    from planner.oracle_worker import _run_with_timeout
    called = []
    out = _run_with_timeout(lambda: 7, lambda: called.append(1), timeout_s=5)
    assert out == 7
    assert called == []                     # watchdog did not fire


def test_run_with_timeout_fires_watchdog_on_hang():
    import threading
    from planner.oracle_worker import _run_with_timeout
    unblocked, fired = threading.Event(), []

    def run_fn():
        unblocked.wait(2)                   # blocks until the watchdog "tears down" -> unblocks it
        return "aborted"

    def on_timeout():
        fired.append(1)
        unblocked.set()                     # teardown breaks the socket -> the blocked run unblocks

    out = _run_with_timeout(run_fn, on_timeout, timeout_s=0.1)
    assert fired == [1] and out == "aborted"
