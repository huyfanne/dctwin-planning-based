from __future__ import annotations

import argparse
import json
import pickle
from datetime import date
from pathlib import Path

import pandas as pd

from dcwiz_policy_template import RecommendTemplate
from dctwin.utils import config as dt_config

from planner.beam_search import BeamConfig, BeamPlanner
from planner.forecaster import build_forecaster
from planner.objective import ObjectiveWeights
from planner.oracle import OracleConfig, ParallelEnvOracle
from planner.recommendation import build_recommendation, write_recommendation
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


class WeeklyPlanTemplate(RecommendTemplate):
    """One-shot weekly planner: heuristic search over 3 setpoints, EnergyPlus-scored.

    Overrides run() because the base RecommendTemplate.run() expects a reactive
    dcbrain policy. The oracle owns the weekly run period (via forecast.week_start),
    so we do NOT pass recommendation_timestamp to __call__.
    """

    def initialize(self, *args, **kwargs):
        self.dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        self.week_start = kwargs["week_start"]
        if isinstance(self.week_start, str):
            self.week_start = date.fromisoformat(self.week_start)
        self.days = int(kwargs.get("days", 7))
        self.timesteps_per_hour = int(kwargs.get("timesteps_per_hour", 4))
        self.baseline_energy_kwh = kwargs.get("baseline_energy_kwh")

        # forecaster from the fitted config (fit_forecaster.py output)
        fc_cfg = pickle.loads(Path(kwargs.get("forecaster_config", "models/forecaster.pkl")).read_bytes())
        his = pd.read_csv(fc_cfg["his_csv"])
        room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
        self.forecaster = build_forecaster(fc_cfg["method"], his, room2ite, fc_cfg["his_col_for_room"],
                                          weather_file=fc_cfg.get("weather_file"))

        self.space = DEFAULT_SEARCH_SPACE
        self.oracle = ParallelEnvOracle(
            base_prototxt=self.dt_engine_config,
            project_root=".",
            config=OracleConfig(
                n_workers=int(kwargs.get("n_workers", 8)),
                timesteps_per_hour=self.timesteps_per_hour,
                log_root="log/plan",
            ),
        )
        self.beam = BeamConfig(
            grid=int(kwargs.get("grid", 5)),
            beam_width=int(kwargs.get("beam_width", 5)),
            levels=int(kwargs.get("levels", 3)),
        )
        self.planner = BeamPlanner(self.space, self.oracle, ObjectiveWeights(), self.beam)
        # satisfy base-class attribute presence (we override run, so these are unused)
        self.policy = self.planner
        self.obs = None
        self.data_file = kwargs.get("recommendation_out", "log/recommendation.json")

    def run(self, *args, **kwargs):
        from planner.pipeline import PlanRequest, run_weekly_plan
        from pathlib import Path
        from planner.recommendation import write_recommendation
        from dctwin.utils import config as dt_config

        rec = run_weekly_plan(
            PlanRequest(week_start=self.week_start, days=self.days,
                        grid=self.beam.grid, beam_width=self.beam.beam_width,
                        levels=self.beam.levels,
                        timesteps_per_hour=self.timesteps_per_hour),
            evaluator=self.oracle,
            forecaster=self.forecaster,
            baseline_energy_kwh=self.baseline_energy_kwh,
        )
        out = Path(dt_config.LOG_DIR) / "recommendation.json"
        write_recommendation(str(out), rec)
        write_recommendation("log/recommendation.json", rec)
        self.logger.info(f"Weekly recommendation written to {out} (status={rec['status']})")
        return rec


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the weekly Digital-Twin planner")
    parser.add_argument("--week-start", required=True, help="YYYY-MM-DD (Monday)")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--forecaster", default="models/forecaster.pkl")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--grid", type=int, default=5)
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--n-workers", type=int, default=8)
    args = parser.parse_args()

    WeeklyPlanTemplate()(
        dt_engine_config=args.dt,
        forecaster_config=args.forecaster,
        week_start=args.week_start,
        days=args.days,
        grid=args.grid,
        beam_width=args.beam_width,
        levels=args.levels,
        n_workers=args.n_workers,
    )
    print("Weekly plan complete")
