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


@dataclass
class RobustResult:
    winner: Setpoints
    winner_kpi: WeeklyKPI            # the calibrated NOMINAL kpi (twin's best estimate)
    robust_feasible: bool            # feasible in EVERY scenario
    cvar_energy_kwh: float           # CVaR_alpha of energy across scenarios
    confidence_bands: dict           # {kpi_key: {"p50","p90","max"}}
    n_scenarios: int


def _cvar(values: list, alpha: float) -> float:
    """Mean of the worst (1-alpha) upper tail (higher energy = worse)."""
    if not values:
        return math.inf
    k = max(1, math.ceil((1.0 - alpha) * len(values)))
    return sum(sorted(values, reverse=True)[:k]) / k


def _quantile(values: list, q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def robust_select(finalists: list, scenario_kpis: list,
                  weights: ObjectiveWeights, alpha: float = 0.8) -> RobustResult:
    """finalists: list of (Setpoints, WeeklyKPI, score). scenario_kpis[i]: the list
    of per-scenario WeeklyKPI for finalist i. Worst-case inlet feasibility (feasible
    in EVERY scenario) + CVaR_alpha energy; ties broken by lowest CVaR energy. If no
    finalist is robust-feasible, fall back to the least-bad by CVaR energy."""
    n_scen = len(scenario_kpis[0]) if scenario_kpis else 0
    robust_feasible = [
        bool(ks) and all(is_feasible(k, weights) for k in ks) for ks in scenario_kpis
    ]
    pool = [i for i, ok in enumerate(robust_feasible) if ok] or list(range(len(finalists)))

    def cvar_e(i):
        return _cvar([k.total_hvac_energy_kwh for k in scenario_kpis[i]], alpha)

    win = min(pool, key=cvar_e)
    bands = {}
    for key in ROBUST_KEYS:
        vals = [getattr(k, _RKEY_FIELD[key]) for k in scenario_kpis[win]]
        bands[key] = {"p50": _quantile(vals, 0.5), "p90": _quantile(vals, 0.9), "max": max(vals)}
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=n_scen)
