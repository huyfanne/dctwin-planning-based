from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from planner.beam_search import BeamConfig, BeamPlanner
from planner.calibrator import SIGMA_PRIOR
from planner.objective import ObjectiveWeights
from planner.recommendation import build_recommendation, safest_fallback
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
    time_block: bool = False


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
    baseline_setpoints: Optional[Setpoints] = None,
    energy_scope: Optional[str] = None,
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

    # Real "as-operated" baseline: evaluate the plant's current setpoints once on the
    # same forecast week so energy_reduction_vs_baseline is honest (vs the old UI 450
    # placeholder). One extra full-week eval; calibrated like the plan KPI for fairness.
    baseline_kpi = None
    if baseline_setpoints is not None and baseline_energy_kwh is None:
        base_kpi = evaluator.evaluate([baseline_setpoints], forecast)[0]
        if calibration is not None:
            base_kpi = calibration.apply(base_kpi)
        baseline_energy_kwh = base_kpi.total_hvac_energy_kwh
        baseline_kpi = base_kpi

    planner = BeamPlanner(space, evaluator, weights, beam, calibration=calibration)
    result = planner.plan(forecast, on_level=on_level, on_eval=on_eval)

    robust = None
    if robust_rerank_fn is not None and result.beam_finalists:
        robust = robust_rerank_fn(result.beam_finalists, forecast)
        # If the energy-optimal finalists are all fragile (robust-infeasible under the
        # perturbed-plant ensemble), don't just block: evaluate margin-increasing variants
        # (more cooling) and recommend the CHEAPEST genuinely-robust one. Only stay
        # blocked_unsafe if even the max-cooling fallback can't hold the cap. This turns the
        # common "energy optimum sits on a cooling cliff" case into a safe, slightly-costlier
        # recommendation instead of an un-actionable block.
        if robust is not None and not robust.robust_feasible:
            from planner.objective import score as _obj_score
            from planner.robust import safety_ladder
            variants = safety_ladder(robust.winner, space)
            # The as-operated baseline is a known safe operating point — include it so the
            # cheapest robust plan is, at worst, ~the baseline (a 0% reduction), never the
            # energy-wasteful max-cooling corner.
            if baseline_setpoints is not None:
                variants = variants + [baseline_setpoints]
            if variants:
                vk = evaluator.evaluate(variants, forecast)
                if calibration is not None:
                    vk = [calibration.apply(k) for k in vk]
                vfinalists = [(sp, k, _obj_score(k, weights)) for sp, k in zip(variants, vk)]
                robust2 = robust_rerank_fn(vfinalists, forecast)
                if robust2 is not None and robust2.robust_feasible:
                    robust = dataclasses.replace(robust2, robust_substituted=True)

    if robust is not None:
        # when the robust ensemble ran, robust feasibility is decisive
        best, kpi = robust.winner, robust.winner_kpi
        raw = robust.winner_kpi_raw or robust.winner_kpi
        status = "pending_approval" if robust.robust_feasible else "blocked_unsafe"
    elif result.feasible:
        best, kpi, raw, status = result.best, result.best_kpi, result.best_kpi_raw, "pending_approval"
    elif result.coarse:
        # No feasible candidate: pick the safest already-evaluated coarse point (fewest inlet
        # violations, then least energy) instead of a hand-picked corner — data-driven, no re-eval.
        idx = safest_fallback([c[1] for c in result.coarse])
        best, kpi, raw, status = (result.coarse[idx][0], result.coarse[idx][1],
                                  result.coarse[idx][3], "infeasible_fallback")
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        fb_kpi = evaluator.evaluate([fb], forecast)[0]
        kpi = calibration.apply(fb_kpi) if calibration is not None else fb_kpi
        best, raw, status = fb, fb_kpi, "infeasible_fallback"

    schedule = None
    if request.time_block and status == "pending_approval" and hasattr(evaluator, "evaluate_schedules"):
        from planner.schedule_search import refine_schedule
        sched_res = refine_schedule(best, evaluator, weights, forecast, calibration)
        schedule = sched_res.schedule
        best, kpi, raw = schedule.setpoints[0], sched_res.kpi, sched_res.kpi_raw   # top-level mirrors DAY block

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
        schedule=schedule,
        degenerate_no_signal=result.degenerate_no_signal,
        baseline_setpoints=baseline_setpoints,
        energy_scope=energy_scope,
        baseline_kpi=baseline_kpi,
    )
