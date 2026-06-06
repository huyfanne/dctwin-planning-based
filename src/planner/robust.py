"""Scenario/ensemble-robust setpoint selection (P2b): evaluate the beam finalists
across an ensemble of perturbed-plant scenarios and pick the robust winner —
worst-case inlet feasibility + CVaR energy — with confidence bands."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from planner.calibrator import Calibration
from planner.objective import ObjectiveWeights, is_feasible
from planner.plant import DEFAULT_PLANT, Perturbation, PlantConfig
from planner.types import Setpoints, WeeklyKPI

ROBUST_KEYS = ("total_hvac_energy_kwh", "inlet_temp_max_c", "pue_mean")
_RKEY_FIELD = {
    "total_hvac_energy_kwh": "total_hvac_energy_kwh",
    "inlet_temp_max_c": "inlet_temp_max",
    "pue_mean": "pue_mean",
}


def make_scenarios(base: PlantConfig, n: int, spread: float) -> list[PlantConfig]:
    """N deterministic PlantConfig draws: scale EVERY perturbation factor by
    evenly-spaced multipliers in [1-spread, 1+spread]. n<=1 -> [base]."""
    if n <= 1:
        return [base]
    out = []
    for i in range(n):
        m = (1.0 - spread) + (2.0 * spread) * i / (n - 1)
        out.append(PlantConfig(tuple(
            Perturbation(p.table, p.field, p.factor * m) for p in base.perturbations)))
    return out


def scenario_spread(calibration: Optional[Calibration], base_spread: float = 0.1,
                    sigma_ref: float = 1.0) -> float:
    """Ensemble half-width: a prior at cold-start, widened by the calibrated inlet
    uncertainty so the ensemble brackets the observed mismatch."""
    if calibration is None or calibration.n_weeks == 0:
        return base_spread
    return base_spread * (1.0 + calibration.sigma_for("inlet_temp_max_c") / sigma_ref)
