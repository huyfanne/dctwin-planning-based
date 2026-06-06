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
    calibration=None,
    robust_rerank_fn=None,
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

    planner = BeamPlanner(space, evaluator, weights, beam, calibration=calibration)
    result = planner.plan(forecast, on_level=on_level, on_eval=on_eval)

    robust = None
    if robust_rerank_fn is not None and result.beam_finalists:
        robust = robust_rerank_fn(result.beam_finalists, forecast)
        result.best, result.best_kpi = robust.winner, robust.winner_kpi

    if result.feasible:
        best, kpi, status = result.best, result.best_kpi, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        fb_kpi = evaluator.evaluate([fb], forecast)[0]
        kpi = calibration.apply(fb_kpi) if calibration is not None else fb_kpi
        best, status = fb, "infeasible_fallback"

    return build_recommendation(
        setpoints=best, kpi=kpi, week_start=request.week_start, days=request.days,
        forecast_method=getattr(forecast, "method", "persistence"),
        search_meta={"evals": result.evals, "beam_width": beam.beam_width, "levels": beam.levels},
        baseline_energy_kwh=baseline_energy_kwh, status=status,
        robust_feasible=(robust.robust_feasible if robust else None),
        cvar_energy_kwh=(robust.cvar_energy_kwh if robust else None),
        confidence_bands=(robust.confidence_bands if robust else None),
        n_scenarios=(robust.n_scenarios if robust else None),
        calibration_version=(calibration.version if calibration is not None else None),
    )
