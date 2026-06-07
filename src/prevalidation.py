from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from planner.kpi import OracleSettings, step_trajectory
from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.trajectory import write_trajectory_csv
from planner.types import Setpoints, WeeklyKPI
from planner.validation import validation_metrics, render_report


def set_status(recommendation_path: str, status: str) -> None:
    rec = json.loads(Path(recommendation_path).read_text())
    rec["status"] = status
    Path(recommendation_path).write_text(json.dumps(rec, indent=2))


class _Forecast:
    def __init__(self, week_start: date):
        self.week_start = week_start
    def materialize(self, root):
        pass


def _setpoints_from_rec(rec: dict) -> Setpoints:
    s = rec["setpoints"]
    return Setpoints(s["crah_supply_air_temperature_c"],
                     s["crah_supply_air_mass_flow_rate_kg_s"],
                     s["chilled_water_supply_temperature_c"])


def run_prevalidation(recommendation_path: str, evaluator, baseline: Setpoints,
                      out_dir: str = "log/prevalidation", project_root: str = ".") -> dict:
    """Independently replay the RECOMMENDED setpoints (not the stored predicted_kpis)
    and compare against a baseline run. Emits report.md + trajectory_ai.csv into out_dir."""
    rec = json.loads(Path(recommendation_path).read_text())
    recommended = _setpoints_from_rec(rec)
    week_start = date.fromisoformat(rec["week_start"])
    forecast = _Forecast(week_start)

    # independent AI replay (+ trajectory if the evaluator can produce one)
    if hasattr(evaluator, "replay_with_trajectory"):
        ai_kpi, samples = evaluator.replay_with_trajectory(recommended, forecast)
        rows = step_trajectory(samples, hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    else:
        ai_kpi = evaluator.evaluate([recommended], forecast)[0]
        rows = []
    baseline_kpi = evaluator.evaluate([baseline], forecast)[0]

    metrics = validation_metrics(ai_kpi, baseline_kpi)
    report = render_report(metrics, plan_id=rec["plan_id"])
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "report.md").write_text(report)
    if rows:
        write_trajectory_csv(rows, str(Path(out_dir) / "trajectory_ai.csv"))
    return metrics


def run_prevalidation_with_oracle(recommendation_path: str, dt_engine_config: str,
                                  baseline: Setpoints, out_dir: str = "log/prevalidation",
                                  project_root: str = ".") -> dict:
    """Production wrapper: build the real ParallelEnvOracle and run an independent replay."""
    orc = ParallelEnvOracle(base_prototxt=dt_engine_config, project_root=project_root,
                            config=OracleConfig(n_workers=1, use_process_pool=False,
                                                log_root=str(Path(out_dir) / "oracle")))
    return run_prevalidation(recommendation_path, evaluator=orc, baseline=baseline,
                             out_dir=out_dir, project_root=project_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-validation + expert approval gate")
    parser.add_argument("--recommendation", default="log/recommendation.json")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--approve", action="store_true", help="mark plan approved")
    parser.add_argument("--reject", action="store_true", help="mark plan rejected")
    args = parser.parse_args()

    if args.approve:
        set_status(args.recommendation, "approved")
        print("approved")
    elif args.reject:
        set_status(args.recommendation, "rejected")
        print("rejected")
    else:
        from planner.types import DEFAULT_SEARCH_SPACE as S
        baseline = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)   # coolest SAT/CHW, max flow
        run_prevalidation_with_oracle(args.recommendation, args.dt, baseline)
