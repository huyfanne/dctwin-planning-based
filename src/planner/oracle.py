from __future__ import annotations

import concurrent.futures as cf
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)

from planner.kpi import OracleSettings
from planner.oracle_worker import EvalTask, evaluate_one, evaluate_one_with_samples, evaluate_one_schedule
from planner.types import Evaluator, Setpoints, WeeklyKPI
from planner.week_config import write_week_config


@dataclass
class OracleConfig:
    n_workers: int = 8
    timeout_s: float = 300.0            # per-candidate wall-clock cap (enforced in the worker)
    timesteps_per_hour: int = 4         # -> hours_per_step = 1/this
    log_root: str = "log/oracle"
    use_process_pool: bool = True       # False = serial (for tests/debug)
    settings: OracleSettings = field(default_factory=OracleSettings)
    # BCVTB host the EnergyPlus container connects back to. dctwin's default
    # ("host.docker.internal") does not resolve inside a Linux bridge container,
    # so we use the docker0 bridge gateway, which the container can reach and where
    # the host's 0.0.0.0-bound socket is already listening.
    bcvtb_host: str = "172.17.0.1"
    # Scope the thermal KPI (inlet/zone) to the controlled hall; we only actuate
    # the 1F 2A ACUs, so other halls' sensors are uncontrollable noise ("" = all).
    monitored_hall: str = "1f 2a"
    # Stall watchdog: abandon a batch's stragglers if NO future completes within this
    # window while some are pending. None -> 1.5 * timeout_s. A healthy batch always
    # completes something within timeout_s (the per-candidate worker watchdog), so a
    # silent window means a wedged worker or a lost future.
    stall_window_s: Optional[float] = None


def _batch_deadline(timeout_s: float, n_tasks: int, n_workers: int) -> float:
    """Wall-clock backstop for a whole batch. Each parallel wave is bounded by the
    per-candidate timeout, so a batch needs ~ceil(n_tasks / n_workers) waves (+1 slack).
    The old `timeout_s * n_tasks` assumed serial execution, so one hung worker could
    block the batch for hours."""
    waves = math.ceil(max(n_tasks, 1) / max(n_workers, 1))
    return timeout_s * (waves + 1)


def _collect_with_stall_guard(futs: dict, results: list, on_result, cfg) -> None:
    """Collect pool futures into `results` (pre-filled infeasible) with TWO backstops:

    1. STALL watchdog — if no future completes within ~1.5x the per-candidate timeout
       while futures are pending, abandon the stragglers as infeasible. The worker
       watchdog bounds every healthy candidate to timeout_s, so a silent window can
       only mean a wedged worker or a future that will never resolve. (Incident
       gds-2024-12-06-a368bc: 2 of 125 futures never resolved while every pool worker
       sat idle; the batch then waited on backstop 2 — 70 minutes at that config.)
    2. The absolute batch deadline (waves * timeout_s) as the outer bound.
    """
    stall = (cfg.stall_window_s if cfg.stall_window_s and cfg.stall_window_s > 0
             else 1.5 * cfg.timeout_s)
    deadline = time.monotonic() + _batch_deadline(cfg.timeout_s, len(futs), cfg.n_workers)
    pending = set(futs)
    while pending:
        budget = deadline - time.monotonic()
        if budget <= 0:
            logger.warning("oracle batch deadline hit: abandoning %d candidate(s)",
                           len(pending))
            break
        done, pending = cf.wait(pending, timeout=min(stall, budget),
                                return_when=cf.FIRST_COMPLETED)
        if not done:
            logger.warning("oracle batch stalled (%.0fs without a completion): "
                           "abandoning %d candidate(s) as infeasible", stall, len(pending))
            break
        for fut in done:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception:  # noqa: BLE001 - worker crash / broken pool
                results[i] = _infeasible()
            if on_result is not None:
                on_result()  # one tick per completed candidate (any order)


def _infeasible() -> WeeklyKPI:
    return WeeklyKPI(
        total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
        inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
        rh_violation_steps=10 ** 9, feasible=False,
    )


class ParallelEnvOracle(Evaluator):
    """Score candidate weekly setpoints with real full-week EnergyPlus runs."""

    def __init__(self, base_prototxt: str, config: Optional[OracleConfig] = None,
                 project_root: str = ".", worker_fn=None, sample_worker_fn=None):
        self.base_prototxt = base_prototxt
        self.config = config or OracleConfig()
        self.project_root = project_root
        self._worker = worker_fn if worker_fn is not None else evaluate_one
        self._sample_worker = sample_worker_fn

    def evaluate(self, candidates: Sequence[Setpoints],
                 forecast: Optional[Any] = None,
                 on_result: Optional[Callable[[], None]] = None) -> list[WeeklyKPI]:
        cfg = self.config
        hours_per_step = 1.0 / cfg.timesteps_per_hour

        # 1) materialize the forecast (workload schedules) + write the weekly config
        if forecast is not None and hasattr(forecast, "materialize"):
            forecast.materialize(self.project_root)
        # Docker volume mounts require ABSOLUTE host paths (a relative dir is
        # misread as a named volume -> 400 "invalid characters" error), so resolve
        # log_root and the config path up front.
        log_root = Path(cfg.log_root).resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        if forecast is not None and getattr(forecast, "week_start", None) is not None:
            week_cfg_path = str(log_root / "week.prototxt")
            self._write_week_cfg(forecast, week_cfg_path)
        else:
            week_cfg_path = str(Path(self.base_prototxt).resolve())

        # 2) build one task per candidate with a unique ABSOLUTE per-candidate log dir
        tasks = [
            EvalTask(
                candidate=c.as_tuple(),
                week_config_path=week_cfg_path,
                log_dir=str(log_root / f"cand-{i:04d}"),
                hours_per_step=hours_per_step,
                settings_kwargs=cfg.settings.__dict__,
                bcvtb_host=cfg.bcvtb_host,
                monitored_hall=cfg.monitored_hall,
                timeout_s=cfg.timeout_s,
            )
            for i, c in enumerate(candidates)
        ]

        # 3) run (serial for tests, process pool in production)
        if not cfg.use_process_pool:
            out: list[WeeklyKPI] = []
            for t in tasks:
                out.append(self._safe_run(t))
                if on_result is not None:
                    on_result()
            return out

        results: list[WeeklyKPI] = [_infeasible()] * len(tasks)
        ex = cf.ProcessPoolExecutor(max_workers=cfg.n_workers)
        futs = {ex.submit(self._worker, t): i for i, t in enumerate(tasks)}
        try:
            _collect_with_stall_guard(futs, results, on_result, cfg)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return results

    def replay_with_trajectory(self, setpoints: Setpoints, forecast: Optional[Any] = None):
        """Inline single-candidate run that ALSO returns the per-step StepSample list.
        Used by pre-validation to emit a trajectory CSV (never the process pool)."""
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
        task = EvalTask(
            candidate=setpoints.as_tuple(), week_config_path=week_cfg_path,
            log_dir=str(log_root / "replay"), hours_per_step=hours_per_step,
            settings_kwargs=cfg.settings.__dict__, bcvtb_host=cfg.bcvtb_host,
            monitored_hall=cfg.monitored_hall, timeout_s=cfg.timeout_s)
        worker = self._sample_worker or evaluate_one_with_samples
        return worker(task)

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
                     monitored_hall=cfg.monitored_hall, schedule=s, timeout_s=cfg.timeout_s)
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
        try:
            _collect_with_stall_guard(futs, results, on_result, cfg)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return results

    def _write_week_cfg(self, forecast, week_cfg_path):
        return write_week_config(
            self.base_prototxt, forecast.week_start, week_cfg_path,
            timesteps_per_hour=self.config.timesteps_per_hour,
            weather_file=getattr(forecast, "weather_file", None))

    def _safe_run(self, task: EvalTask) -> WeeklyKPI:
        try:
            return self._worker(task)
        except Exception:  # noqa: BLE001
            return _infeasible()
