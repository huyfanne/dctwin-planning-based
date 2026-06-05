from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from planner.kpi import OracleSettings
from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.types import Setpoints, WeeklyKPI
from planner.validation import validation_metrics, render_report


def set_status(recommendation_path: str, status: str) -> None:
    rec = json.loads(Path(recommendation_path).read_text())
    rec["status"] = status
    Path(recommendation_path).write_text(json.dumps(rec, indent=2))


def _kpi_from_predicted(rec: dict) -> WeeklyKPI:
    k = rec["predicted_kpis"]
    return WeeklyKPI(
        total_hvac_energy_kwh=k["total_hvac_energy_kwh"], pue_mean=k["pue_mean"],
        inlet_temp_max=k["inlet_temp_max_c"], inlet_violation_steps=k["inlet_violation_steps"],
        rh_violation_steps=0, feasible=True,
    )


class _Forecast:
    def __init__(self, week_start: date):
        self.week_start = week_start
    def materialize(self, root):
        pass


def run_prevalidation(recommendation_path: str, dt_engine_config: str,
                      baseline: Setpoints, project_root: str = ".") -> dict:
    """Compare the recommended plan (predicted KPIs) against a baseline run."""
    rec = json.loads(Path(recommendation_path).read_text())
    ai_kpi = _kpi_from_predicted(rec)

    orc = ParallelEnvOracle(base_prototxt=dt_engine_config, project_root=project_root,
                            config=OracleConfig(n_workers=1, use_process_pool=False,
                                                log_root="log/prevalidation"))
    week_start = date.fromisoformat(rec["week_start"])
    baseline_kpi = orc.evaluate([baseline], forecast=_Forecast(week_start))[0]

    metrics = validation_metrics(ai_kpi, baseline_kpi)
    report = render_report(metrics, plan_id=rec["plan_id"])
    Path("log/prevalidation").mkdir(parents=True, exist_ok=True)
    Path("log/prevalidation/report.md").write_text(report)
    print(report)
    return metrics


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
        # conservative baseline: coolest SAT/CHW, max flow
        from planner.types import DEFAULT_SEARCH_SPACE as S
        baseline = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)
        run_prevalidation(args.recommendation, args.dt, baseline)
