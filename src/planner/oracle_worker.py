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
        if not done:
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
