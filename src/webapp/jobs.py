from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from webapp.store import PlanStore

logger = logging.getLogger(__name__)

# runner(plan_id, params, store, progress_cb) -> None
RunnerFn = Callable[[str, dict, PlanStore, Callable[[dict], None]], None]


class JobRunner:
    """Single-worker background job runner (one plan at a time; each saturates the CPU)."""

    def __init__(self, store: PlanStore, runner: Optional[RunnerFn] = None):
        self.store = store
        self.runner = runner or run_plan_job
        self._q: "queue.Queue[Optional[tuple[str, dict]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)  # unblock the worker
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def submit(self, plan_id: str, params: dict) -> None:
        self._q.put((plan_id, params))

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            plan_id, params = item
            self.store.set_status(plan_id, "running")
            try:
                self.runner(plan_id, params, self.store,
                            lambda p, pid=plan_id: self.store.write_progress(pid, p))
            except Exception:  # noqa: BLE001
                logger.exception("plan %s failed", plan_id)
                self.store.set_status(plan_id, "failed")


def run_plan_job(plan_id: str, params: dict, store: PlanStore,
                 progress_cb: Callable[[dict], None]) -> None:
    """Production runner: run the real framework and persist the recommendation.

    Imported lazily so the unit tests (which inject a fake runner) need no dctwin.
    """
    from datetime import date

    import pandas as pd
    import json as _json
    from pathlib import Path

    from dctwin.utils import config as dt_config
    from planner.forecaster import StatisticalForecaster
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.pipeline import PlanRequest, run_weekly_plan

    plan_dir = store.plan_dir(plan_id)
    dt_config.set_log_dir(str(plan_dir))

    dt_cfg = params.get("dt", "configs/dt/dt.prototxt")
    fc_cfg = pickle_load(params.get("forecaster", "models/forecaster.pkl"))
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = _json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])

    oracle = ParallelEnvOracle(
        base_prototxt=dt_cfg, project_root=".",
        config=OracleConfig(n_workers=int(params.get("n_workers", 8)),
                            timesteps_per_hour=int(params.get("timesteps_per_hour", 4)),
                            log_root=str(plan_dir / "oracle")),
    )

    def on_level(level, evals, best):
        progress_cb({"level": level, "evals": evals, "best_score": best})

    rec = run_weekly_plan(
        PlanRequest(week_start=date.fromisoformat(params["week_start"]),
                    days=int(params.get("days", 7)),
                    grid=int(params.get("grid", 5)),
                    beam_width=int(params.get("beam_width", 5)),
                    levels=int(params.get("levels", 3)),
                    timesteps_per_hour=int(params.get("timesteps_per_hour", 4))),
        evaluator=oracle, forecaster=forecaster,
        baseline_energy_kwh=params.get("baseline_energy_kwh"),
        on_level=on_level,
    )
    store.save_recommendation(plan_id, rec)


def pickle_load(path: str) -> dict:
    import pickle
    from pathlib import Path
    return pickle.loads(Path(path).read_bytes())
