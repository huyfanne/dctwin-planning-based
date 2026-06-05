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
        Path(cfg.log_root).mkdir(parents=True, exist_ok=True)
        week_cfg_path = str(Path(cfg.log_root) / "week.prototxt")
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
