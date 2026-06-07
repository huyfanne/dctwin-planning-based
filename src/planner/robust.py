"""Scenario/ensemble-robust setpoint selection (P2b): evaluate the beam finalists
across an ensemble of perturbed-plant scenarios and pick the robust winner —
worst-case inlet feasibility + CVaR energy — with confidence bands."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from planner.calibrator import Calibration
from planner.objective import ObjectiveWeights, is_feasible
from planner.plant import DEFAULT_PLANT, Perturbation, PlantConfig, build_plant_prototxt
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
    winner_kpi_raw: WeeklyKPI = None        # the winner's pre-calibration nominal kpi
    robust_substituted: bool = False        # winner != the energy-optimal beam finalist
    scenario_diagnostics: Optional[list] = None   # per-scenario inlet/feasibility for the winner


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
    raw = finalists[win][3] if len(finalists[win]) > 3 else finalists[win][1]
    diagnostics = [
        {"scenario": j,
         "inlet_temp_max_c": scenario_kpis[win][j].inlet_temp_max,
         "feasible": is_feasible(scenario_kpis[win][j], weights)}
        for j in range(n_scen)
    ]
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=n_scen, winner_kpi_raw=raw,
        robust_substituted=(win != 0), scenario_diagnostics=diagnostics)


def make_oracle_robust_rerank(base_prototxt, oracle_config, calibration,
                              weights, n_scenarios, log_root, oracle_cls=None):
    """Build a robust_rerank_fn(finalists, forecast) -> RobustResult that evaluates
    the finalists under N perturbed-plant scenarios (each a real EnergyPlus run).
    `oracle_cls` is injectable for testing (default ParallelEnvOracle)."""
    from pathlib import Path

    if oracle_cls is None:
        from planner.oracle import ParallelEnvOracle
        oracle_cls = ParallelEnvOracle

    spread = scenario_spread(calibration)
    scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)

    def rerank(finalists, forecast):
        setpoints = [f[0] for f in finalists]
        per_finalist = [[] for _ in finalists]
        for j, sc in enumerate(scenarios):
            sdir = str(Path(log_root) / f"scenario-{j:02d}")
            sproto = build_plant_prototxt(base_prototxt, sc, sdir)
            oracle = oracle_cls(
                base_prototxt=sproto, project_root=".",
                config=replace(oracle_config, log_root=str(Path(sdir) / "oracle")))
            for i, k in enumerate(oracle.evaluate(setpoints, forecast=forecast)):
                per_finalist[i].append(k)
        return robust_select(finalists, per_finalist, weights)

    return rerank
