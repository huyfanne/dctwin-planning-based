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
