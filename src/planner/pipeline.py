from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from planner.beam_search import BeamConfig, BeamPlanner
from planner.calibrator import SIGMA_PRIOR
from planner.objective import ObjectiveWeights
from planner.recommendation import build_recommendation
from planner.types import DEFAULT_SEARCH_SPACE, Evaluator, Setpoints


K_SIGMA = 1.0   # inlet pre-tighten = K_SIGMA * sigma_inlet (on by default)


def apply_forecast_margin(weights: "ObjectiveWeights", calibration,
                          k_sigma: float = K_SIGMA) -> "ObjectiveWeights":
    """Set inlet_forecast_margin = k * sigma_inlet so the search treats the inlet cap
    as (cap - margin). sigma comes from calibration once realized weeks exist, else the
    cold-start SIGMA_PRIOR. Idempotent (sets, never accumulates). calibration None -> unchanged."""
    if calibration is None:
        return weights
    sigma = (calibration.sigma_for("inlet_temp_max_c") if calibration.n_weeks > 0
             else SIGMA_PRIOR["inlet_temp_max_c"])
    return dataclasses.replace(weights, inlet_forecast_margin=k_sigma * sigma)


@dataclass
class PlanRequest:
    week_start: date
    days: int = 7
    grid: int = 5
    beam_width: int = 5
    levels: int = 3
    timesteps_per_hour: int = 4


def validate_plan_request(request: "PlanRequest", weights: ObjectiveWeights,
                          beam: BeamConfig) -> None:
    """Fail-fast BEFORE any EnergyPlus run (spec §11). Raises ValueError on a
    misconfigured request so a bad plan never launches hundreds of Docker runs."""
    if beam.grid < 2:
        raise ValueError(f"grid must be >= 2, got {beam.grid}")
    if beam.beam_width < 1:
        raise ValueError(f"beam_width must be >= 1, got {beam.beam_width}")
    if beam.levels < 0:
        raise ValueError(f"levels must be >= 0, got {beam.levels}")
    if beam.max_evals <= 0:
        raise ValueError(f"max_evals must be > 0, got {beam.max_evals}")
    if request.days < 1:
        raise ValueError(f"days must be >= 1, got {request.days}")
    for name in ("lambda_temp", "lambda_rh", "lambda_zone"):
        v = getattr(weights, name)
        if v < 0:
            raise ValueError(f"objective weight {name} must be >= 0, got {v}")


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
    weights = apply_forecast_margin(weights, calibration)
    beam = BeamConfig(grid=request.grid, beam_width=request.beam_width, levels=request.levels)
    validate_plan_request(request, weights, beam)

    n_steps = request.days * 24 * request.timesteps_per_hour
    forecast = forecaster.forecast(request.week_start, n_steps)

    import os
    _wf = getattr(forecast, "weather_file", None)
    forecast_meta = {
        "method": getattr(forecast, "method", "persistence"),
        "weather": os.path.basename(_wf) if _wf else "TMY-window",
        "bands": getattr(forecast, "bands", None) is not None,
    }

    planner = BeamPlanner(space, evaluator, weights, beam, calibration=calibration)
    result = planner.plan(forecast, on_level=on_level, on_eval=on_eval)

    robust = None
    if robust_rerank_fn is not None and result.beam_finalists:
        robust = robust_rerank_fn(result.beam_finalists, forecast)

    if robust is not None:
        # when the robust ensemble ran, robust feasibility is decisive
        best, kpi = robust.winner, robust.winner_kpi
        raw = robust.winner_kpi_raw or robust.winner_kpi
        status = "pending_approval" if robust.robust_feasible else "blocked_unsafe"
    elif result.feasible:
        best, kpi, raw, status = result.best, result.best_kpi, result.best_kpi_raw, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        fb_kpi = evaluator.evaluate([fb], forecast)[0]
        kpi = calibration.apply(fb_kpi) if calibration is not None else fb_kpi
        best, raw, status = fb, fb_kpi, "infeasible_fallback"

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
        raw_kpi=raw,
        robust_substituted=(robust.robust_substituted if robust else False),
        scenario_diagnostics=(robust.scenario_diagnostics if robust else None),
        scenarios_ok=(robust.scenarios_ok if robust else None),
        forecast_meta=forecast_meta,
        inlet_forecast_margin=weights.inlet_forecast_margin,
        k_sigma=K_SIGMA,
    )
