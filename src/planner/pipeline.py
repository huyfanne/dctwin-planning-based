from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from planner.beam_search import BeamConfig, BeamPlanner
from planner.objective import ObjectiveWeights
from planner.recommendation import build_recommendation
from planner.types import DEFAULT_SEARCH_SPACE, Evaluator, Setpoints


@dataclass
class PlanRequest:
    week_start: date
    days: int = 7
    grid: int = 5
    beam_width: int = 5
    levels: int = 3
    timesteps_per_hour: int = 4


def run_weekly_plan(
    request: PlanRequest,
    evaluator: Evaluator,
    forecaster,
    baseline_energy_kwh: Optional[float] = None,
    weights: Optional[ObjectiveWeights] = None,
    on_level: Optional[Callable[[int, int, float], None]] = None,
    on_eval: Optional[Callable[[int], None]] = None,
) -> dict:
    """Forecast -> best-first search -> recommendation dict. The DRY planning core.

    `evaluator` is the scoring oracle (ParallelEnvOracle in production, MockEvaluator
    in tests). `forecaster` must expose `.method` and `.forecast(week_start, n_steps)`.
    """
    space = DEFAULT_SEARCH_SPACE
    weights = weights or ObjectiveWeights()
    beam = BeamConfig(grid=request.grid, beam_width=request.beam_width, levels=request.levels)

    n_steps = request.days * 24 * request.timesteps_per_hour
    forecast = forecaster.forecast(request.week_start, n_steps)

    planner = BeamPlanner(space, evaluator, weights, beam)
    result = planner.plan(forecast, on_level=on_level, on_eval=on_eval)

    if result.feasible:
        best, kpi, status = result.best, result.best_kpi, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        kpi = evaluator.evaluate([fb], forecast)[0]
        best, status = fb, "infeasible_fallback"

    return build_recommendation(
        setpoints=best, kpi=kpi, week_start=request.week_start, days=request.days,
        forecast_method=getattr(forecast, "method", "persistence"),
        search_meta={"evals": result.evals, "beam_width": beam.beam_width, "levels": beam.levels},
        baseline_energy_kwh=baseline_energy_kwh, status=status,
    )
