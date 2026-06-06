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
    """Single-worker background runner for plan + deploy jobs (one at a time)."""

    def __init__(self, store: PlanStore, runner: Optional[RunnerFn] = None,
                 deploy_runner: Optional[Callable] = None):
        self.store = store
        self.runner = runner or run_plan_job
        self.deploy_runner = deploy_runner or run_deploy_job
        self._q: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def submit(self, plan_id: str, params: dict) -> None:
        self._q.put(("plan", plan_id, params))

    def submit_deploy(self, plan_id: str) -> None:
        self._q.put(("deploy", plan_id, None))

    def run_deploy_sync(self, plan_id: str) -> None:
        self.store.set_status(plan_id, "deploying")
        try:
            self.deploy_runner(plan_id, self.store,
                               lambda p, pid=plan_id: self.store.write_progress(pid, p))
        except Exception:  # noqa: BLE001
            logger.exception("deploy %s failed", plan_id)
            self.store.set_status(plan_id, "deploy_failed")

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            kind, plan_id, params = item
            if kind == "deploy":
                self.run_deploy_sync(plan_id)
                continue
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

    # shared progress state: on_eval ticks the evaluation count within a level,
    # on_level updates the level + best score when a level completes.
    state = {"level": 0, "evals": 0, "best_score": None}

    def on_level(level, evals, best):
        state.update(level=level, evals=evals, best_score=best)
        progress_cb(dict(state))

    def on_eval(done):
        state["evals"] = done
        progress_cb(dict(state))

    rec = run_weekly_plan(
        PlanRequest(week_start=date.fromisoformat(params["week_start"]),
                    days=int(params.get("days", 7)),
                    grid=int(params.get("grid", 5)),
                    beam_width=int(params.get("beam_width", 5)),
                    levels=int(params.get("levels", 3)),
                    timesteps_per_hour=int(params.get("timesteps_per_hour", 4))),
        evaluator=oracle, forecaster=forecaster,
        baseline_energy_kwh=params.get("baseline_energy_kwh"),
        on_level=on_level, on_eval=on_eval,
    )
    store.save_recommendation(plan_id, rec)


def pickle_load(path: str) -> dict:
    import pickle
    from pathlib import Path
    return pickle.loads(Path(path).read_bytes())


def run_deploy_job(plan_id: str, store: PlanStore,
                   progress_cb: Callable[[dict], None]) -> None:
    """Run the PERTURBED PLANT for the approved week, persist realized KPIs, advance
    the forecaster history. Lazy dctwin import (tests inject a fake deploy_runner)."""
    from datetime import date
    import json as _json
    import pandas as pd
    from pathlib import Path

    from dctwin.utils import config as dt_config
    from deploy import deploy
    from planner.plant import DEFAULT_PLANT, build_plant_prototxt
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.forecaster import StatisticalForecaster
    from planner.history import advance_history

    plan_dir = store.plan_dir(plan_id)
    dt_config.set_log_dir(str(plan_dir / "deploy"))
    rec_path = str(plan_dir / "recommendation.json")
    rec = _json.loads(Path(rec_path).read_text())
    week_start = date.fromisoformat(rec["week_start"])

    fc_cfg = pickle_load("models/forecaster.pkl")
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = _json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    n_steps = int(rec.get("days", 7)) * 24 * 4
    forecast = forecaster.forecast(week_start, n_steps)

    plant_prototxt = build_plant_prototxt("configs/dt/dt.prototxt", DEFAULT_PLANT,
                                          str(plan_dir / "plant"))
    plant_oracle = ParallelEnvOracle(
        base_prototxt=plant_prototxt, project_root=".",
        config=OracleConfig(n_workers=1, timesteps_per_hour=4,
                            log_root=str(plan_dir / "deploy" / "oracle")),
    )

    rec = deploy(rec_path, plant_oracle, forecast=forecast)
    store.save_realized(plan_id, rec["realized_kpis"])
    advance_history(rec["realized_kpis"], week_start, fc_cfg["his_csv"])
    store.set_status(plan_id, "deployed")
