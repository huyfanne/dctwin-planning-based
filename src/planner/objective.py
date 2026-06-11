from __future__ import annotations

import math
from dataclasses import dataclass

from planner.types import WeeklyKPI

INFEASIBLE = math.inf


@dataclass(frozen=True)
class ObjectiveWeights:
    """Soft-penalty weights and hard-constraint tolerances.

    Energy (kWh) is the dominant term; lambdas are small margin tie-breakers.

    The hard feasibility gate uses the integer step COUNTS
    (`inlet_violation_steps`, `rh_violation_steps`); the soft penalty uses the
    float magnitude ACCUMULATORS (`inlet_excess_degc_steps`,
    `rh_excursion_steps`, `zone_temp_band_steps`). An evaluator must set the
    matching count and accumulator consistently. `rh_tol_steps` only takes
    effect when `rh_hard=True`.
    """

    lambda_temp: float = 1.0      # weight on inlet margin excess (deg C * steps)
    lambda_rh: float = 0.2        # weight on humidity excursion
    lambda_zone: float = 0.1      # weight on zone-temp band excursion
    inlet_tol_steps: int = 0      # hard: allowed inlet-violation steps
    rh_hard: bool = False         # if True, rh violations are also a hard constraint
    rh_tol_steps: int = 0
    inlet_forecast_margin: float = 0.0   # deg C: pre-tighten the inlet cap (default off)
    inlet_cap: float = 26.0              # hard ITE inlet limit used by the margin gate


def is_feasible(kpi: WeeklyKPI, w: ObjectiveWeights) -> bool:
    if not kpi.feasible:
        return False
    if kpi.inlet_violation_steps > w.inlet_tol_steps:
        return False
    if w.inlet_forecast_margin > 0.0 and (kpi.inlet_temp_max + w.inlet_forecast_margin) > w.inlet_cap:
        return False
    if w.rh_hard and kpi.rh_violation_steps > w.rh_tol_steps:
        return False
    return True


def score(kpi: WeeklyKPI, w: ObjectiveWeights) -> float:
    """Lower is better. Infeasible candidates score +inf and never enter the beam.

    When a tariff was in play (`weighted_energy_cost` is not None) the cost
    REPLACES raw energy as the dominant term; the soft penalties and the
    feasibility gate are unchanged (safety never trades against price).
    """
    if not is_feasible(kpi, w):
        return INFEASIBLE
    energy_term = (
        kpi.weighted_energy_cost
        if kpi.weighted_energy_cost is not None
        else kpi.total_hvac_energy_kwh
    )
    val = (
        energy_term
        + w.lambda_temp * kpi.inlet_excess_degc_steps
        + w.lambda_rh * kpi.rh_excursion_steps
        + w.lambda_zone * kpi.zone_temp_band_steps
    )
    return val if math.isfinite(val) else INFEASIBLE
