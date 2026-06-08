from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from planner.kpi import OracleSettings, StepSample, aggregate_kpi
from planner.monitor import MonitorSpec
from planner.types import Setpoints, WeeklyKPI

logger = logging.getLogger(__name__)


@dataclass
class EvalTask:
    """Picklable description of one candidate evaluation (process-pool payload)."""

    candidate: tuple[float, float, float]   # (sat, flow, chwst)
    week_config_path: str
    log_dir: str
    hours_per_step: float
    settings_kwargs: dict[str, Any]
    bcvtb_host: str = "172.17.0.1"          # host the EnergyPlus container connects back to
    monitored_hall: str = "1f 2a"           # scope thermal KPI to the controlled hall ("" = all)
    schedule: Optional[Any] = None   # planner.schedule.WeeklySchedule; overrides `candidate` when set
    timeout_s: float = 300.0         # per-candidate wall-clock cap; a hung E+/BCVTB run is aborted after this


def read_step_sample(unwrapped, monitor: MonitorSpec) -> StepSample:
    def g(name):
        return unwrapped.inspect_current_observation(observation_name=name, use_unnormed=True)
    # Sum the controllable-HVAC power channels when discovered; None otherwise so
    # aggregate_kpi falls back to the facility total-IT (mock/legacy envs).
    hvac_power_w = (sum(g(n) for n in monitor.hvac_power_names)
                    if monitor.hvac_power_names else None)
    return StepSample(
        total_power_w=g(monitor.total_power_name),
        it_power_w=g(monitor.it_power_name),
        inlet_temps=[g(n) for n in monitor.inlet_temp_names],
        inlet_rhs=[g(n) for n in monitor.inlet_rh_names],
        zone_temps=[g(n) for n in monitor.zone_temp_names],
        hvac_power_w=hvac_power_w,
    )


def run_episode_with_samples(env, action: np.ndarray, monitor: MonitorSpec,
                             hours_per_step: float, settings: OracleSettings):
    """Like run_episode but also returns the per-step StepSample list."""
    samples: list[StepSample] = []
    env.reset()
    samples.append(read_step_sample(env.unwrapped, monitor))
    done = False
    while not done:
        _obs, _rew, done, _trunc, _info = env.step(action)
        if not done:
            samples.append(read_step_sample(env.unwrapped, monitor))
    return aggregate_kpi(samples, hours_per_step, settings), samples


def run_episode(env, action: np.ndarray, monitor: MonitorSpec,
                hours_per_step: float, settings: OracleSettings) -> WeeklyKPI:
    """Step a (already-built) env to completion with a fixed action; aggregate KPI."""
    kpi, _samples = run_episode_with_samples(env, action, monitor, hours_per_step, settings)
    return kpi


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


def _infeasible(error: str) -> WeeklyKPI:
    return WeeklyKPI(
        total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
        inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
        rh_violation_steps=10 ** 9, feasible=False,
    )


def _configure_backend(env, task) -> None:
    """Point the EnergyPlus container at the reachable BCVTB host AND bound the listening
    socket's accept() to task.timeout_s. dctwin defaults the socket to settimeout(3600), so
    a container that crashes/never connects back leaves the worker blocked in accept() for
    up to an hour; bounding it makes that accept() raise (-> candidate infeasible) instead."""
    backend = getattr(getattr(env, "unwrapped", env), "eplus_backend", None)
    if backend is None:
        return
    if task.bcvtb_host:
        backend._host = task.bcvtb_host
    sock = getattr(backend, "_socket", None)
    if sock is not None and task.timeout_s and task.timeout_s > 0:
        try:
            sock.settimeout(task.timeout_s)
        except Exception:  # noqa: BLE001
            pass


def _teardown_container(env) -> None:
    """Best-effort: unblock a stuck BCVTB recv() (shutdown the connection) and stop+remove
    the EnergyPlus container so a hung/timed-out run doesn't leak it. Fully exception-guarded."""
    backend = getattr(getattr(env, "unwrapped", env), "eplus_backend", None)
    conn = getattr(backend, "_conn", None)
    if conn is not None:
        try:
            conn.shutdown(socket.SHUT_RDWR)   # force a blocked recv() to return
        except Exception:
            pass
    container = getattr(backend, "container", None)
    if container is None:
        return
    try:
        container.stop(timeout=5)
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass


def _run_with_timeout(run_fn, on_timeout, timeout_s):
    """Run run_fn(); if it exceeds timeout_s, a watchdog thread calls on_timeout()
    (which tears down the hung EnergyPlus container -> breaks the BCVTB socket so the
    blocked env.step raises), so a hung run aborts instead of pinning a worker forever.
    Without this, env.step blocks on a dead socket and the worker's finally/teardown
    never runs -> the container leaks and the whole batch stalls.

    This relies on the container's death closing the TCP peer so the host-side recv
    returns; if it doesn't, the BCVTB socket's own 3600s timeout is the ultimate
    fallback and the batch deadline (oracle._batch_deadline) bounds the overall run."""
    import threading
    if not timeout_s or timeout_s <= 0:
        return run_fn()
    done = threading.Event()

    def _watchdog():
        if not done.wait(timeout_s):
            try:
                on_timeout()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        return run_fn()
    finally:
        done.set()


def evaluate_one(task: EvalTask) -> WeeklyKPI:
    """Top-level process-pool target: build env, run one full week, aggregate.

    Any failure (Docker/E+/socket) returns an infeasible WeeklyKPI rather than
    raising, so one bad candidate never aborts the search.
    """
    import dctwin
    from dctwin.utils import config as dt_config
    from planner.env_actions import mapper_from_env
    from planner.monitor import discover_monitor

    # dctwin's per-run post-processing is a fixed 10s sleep + a CSV grouping we
    # never use (we read observations live), so it is pure overhead on every
    # candidate. No-op it in the worker to roughly halve per-eval wall-clock.
    import dctwin.third_parties.eplus.core as _eplus_core
    _eplus_core.EplusBackendMixin._post_process = staticmethod(lambda: None)

    env = None
    try:
        dt_config.set_log_dir(task.log_dir)
        env = dctwin.make_env(env_proto_config=task.week_config_path, reward_fn=lambda x: 0)
        # Override the BCVTB host so socket.cfg points the EnergyPlus container at an
        # address it can actually reach (set before reset(), which writes socket.cfg).
        _configure_backend(env, task)
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env, hall=task.monitored_hall)
        action = broadcaster.expand(Setpoints(*task.candidate))
        return _run_with_timeout(
            lambda: run_episode(env, action, monitor, task.hours_per_step,
                                OracleSettings(**task.settings_kwargs)),
            lambda: _teardown_container(env), task.timeout_s)
    except Exception as exc:  # noqa: BLE001 - intentional: isolate candidate failures
        logger.warning("candidate %s failed: %s", task.candidate, exc)
        return _infeasible(str(exc))
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
            _teardown_container(env)


def evaluate_one_with_samples(task: EvalTask):
    """Like evaluate_one but returns (WeeklyKPI, list[StepSample]). For the inline
    trajectory replay only (never the process pool). Returns (_infeasible(), []) on failure."""
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
        _configure_backend(env, task)
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env, hall=task.monitored_hall)
        action = broadcaster.expand(Setpoints(*task.candidate))
        return _run_with_timeout(
            lambda: run_episode_with_samples(env, action, monitor, task.hours_per_step,
                                             OracleSettings(**task.settings_kwargs)),
            lambda: _teardown_container(env), task.timeout_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trajectory candidate %s failed: %s", task.candidate, exc)
        return _infeasible(str(exc)), []
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
            _teardown_container(env)


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
        _configure_backend(env, task)
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env, hall=task.monitored_hall)
        kpi, _samples = _run_with_timeout(
            lambda: run_episode_schedule(env, broadcaster, task.schedule, monitor,
                                         task.hours_per_step, OracleSettings(**task.settings_kwargs)),
            lambda: _teardown_container(env), task.timeout_s)
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
