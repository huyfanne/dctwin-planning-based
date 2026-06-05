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
    # BCVTB host the EnergyPlus container connects back to. dctwin's default
    # ("host.docker.internal") does not resolve inside a Linux bridge container,
    # so we use the docker0 bridge gateway, which the container can reach and where
    # the host's 0.0.0.0-bound socket is already listening.
    bcvtb_host: str = "172.17.0.1"
    # Scope the thermal KPI (inlet/zone) to the controlled hall; we only actuate
    # the 1F 2A ACUs, so other halls' sensors are uncontrollable noise ("" = all).
    monitored_hall: str = "1f 2a"


def _infeasible() -> WeeklyKPI:
    return WeeklyKPI(
        total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
        inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
        rh_violation_steps=10 ** 9, feasible=False,
    )


class ParallelEnvOracle(Evaluator):
    """Score candidate weekly setpoints with real full-week EnergyPlus runs."""

    def __init__(self, base_prototxt: str, config: Optional[OracleConfig] = None,
                 project_root: str = ".", worker_fn=None):
        self.base_prototxt = base_prototxt
        self.config = config or OracleConfig()
        self.project_root = project_root
        self._worker = worker_fn if worker_fn is not None else evaluate_one

    def evaluate(self, candidates: Sequence[Setpoints],
                 forecast: Optional[Any] = None) -> list[WeeklyKPI]:
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
            write_week_config(self.base_prototxt, forecast.week_start, week_cfg_path,
                              timesteps_per_hour=cfg.timesteps_per_hour)
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
            )
            for i, c in enumerate(candidates)
        ]

        # 3) run (serial for tests, process pool in production)
        if not cfg.use_process_pool:
            return [self._safe_run(t) for t in tasks]

        results: list[WeeklyKPI] = [_infeasible()] * len(tasks)
        ex = cf.ProcessPoolExecutor(max_workers=cfg.n_workers)
        futs = {ex.submit(self._worker, t): i for i, t in enumerate(tasks)}
        # batch deadline backstop: per-candidate cap * number of candidates.
        # (a truly hung worker can't be killed by ProcessPoolExecutor; the dctwin
        #  worker is responsible for its own per-run container kill — spec section 11.)
        deadline = cfg.timeout_s * max(len(tasks), 1)
        try:
            for fut in cf.as_completed(futs, timeout=deadline):
                i = futs[fut]
                try:
                    results[i] = fut.result()
                except Exception:  # noqa: BLE001 - worker crash
                    results[i] = _infeasible()
        except cf.TimeoutError:
            pass  # unfinished candidates remain _infeasible()
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return results

    def _safe_run(self, task: EvalTask) -> WeeklyKPI:
        try:
            return self._worker(task)
        except Exception:  # noqa: BLE001
            return _infeasible()
