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


MIN_SPREAD = 0.02   # physical floor: ~±2% week-scale parameter drift (fouling/filter
                    # loading/fan wear under normal operation). The ensemble hedge never
                    # vanishes however accurate the twin has been — past accuracy is not
                    # immunity to future drift. Discrete failures (a chiller trip) are not
                    # coverable by a continuous ensemble; they are the deploy-blocked
                    # backstop's and live monitoring's job.


def scenario_spread(calibration: Optional[Calibration], base_spread: float = 0.1,
                    sigma_ref: float = 1.0, min_spread: float = MIN_SPREAD) -> float:
    """Ensemble half-width. `base_spread` is the conservative cold-start prior bracketing
    plant-state uncertainty; as deployed weeks MEASURE the twin's accuracy the bracket
    tightens toward the evidence. Scaled by the empirical-Bayes posterior error
    (sigma_post = sqrt((n*s^2 + prior^2)/(n+1)), prior = one pseudo-week) rather than the
    fading-floor sigma: the floor is the right statistic for the nominal safety margin
    (never under-state error at small n) but it stays pinned at the full prior at n=1,
    which froze the ensemble at maximum width exactly when evidence said the twin was
    accurate. Bounded by [min_spread, base_spread]: never wider than the cold-start prior,
    never below the physical drift floor.

    (History: an earlier `* (1 + sigma/ref)` WIDENED the ensemble as sigma rose, so the
    first calibration week doubled the spread and deadlocked the robust gate.)"""
    if calibration is None or calibration.n_weeks == 0 or sigma_ref <= 0:
        return base_spread
    scaled = base_spread * (calibration.sigma_post_for("inlet_temp_max_c") / sigma_ref)
    return min(base_spread, max(min_spread, scaled))


def safety_ladder(best: Setpoints, space, steps: int = 6) -> list:
    """Candidates on the energy<->robustness frontier for the robust gate to SUBSTITUTE
    when the energy optimum `best` is fragile. robust_select recommends the CHEAPEST
    robust-feasible one, so the ladder must buy thermal margin along the CHEAP axes first:

    - CHWST down (toward space.chwst.lb), flow/SAT held: colder chilled water restores
      coil capacity — the binding failure mode in a degraded plant is the coil starving
      at warm CHWST (measured: CHWST 17.8-19 breached the cap in worse-plant scenarios
      while CHWST <=16.9 held 25.3 C) — at a modest chiller-COP cost (~3% energy span).
    - CHWST + SAT down, flow held: SAT is nearly energy-free (~0.5% span) and adds
      supply-air margin.
    - The diagonal toward the max-cooling corner (min SAT, MAX AIRFLOW, min CHWST):
      airflow is the EXPENSIVE axis (~15% fan-energy span), so it is the last resort —
      but its endpoint is the guaranteed-safe fallback.

    Quadratic spacing puts more samples near the cheap end, where the robust boundary
    lives. Out-of-range duplicates dropped."""
    corner = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
    out, seen = [], {best.as_tuple()}

    def add(v: Setpoints) -> None:
        if v.as_tuple() not in seen:
            seen.add(v.as_tuple())
            out.append(v)

    # cheap axes first: chilled-water only, then chw+SAT (flow stays at the optimum's)
    for f in (1.0 / 3.0, 2.0 / 3.0, 1.0):
        chw = best.chwst_c + f * (space.chwst.lb - best.chwst_c)
        add(Setpoints(best.sat_c, best.flow_kg_s, round(chw, 3)))
        sat = best.sat_c + f * (space.sat.lb - best.sat_c)
        add(Setpoints(round(sat, 3), best.flow_kg_s, round(chw, 3)))
    # the all-axes diagonal (incl. airflow) up to the guaranteed-safe corner
    fracs = sorted({round((i / steps) ** 1.5, 4) for i in range(1, steps + 1)})
    for f in fracs:
        add(Setpoints(
            round(best.sat_c + f * (corner.sat_c - best.sat_c), 3),
            round(best.flow_kg_s + f * (corner.flow_kg_s - best.flow_kg_s), 3),
            round(best.chwst_c + f * (corner.chwst_c - best.chwst_c), 3)))
    return out


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
    scenarios_ok: int = 0                   # scenarios that evaluated successfully


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
                  weights: ObjectiveWeights, alpha: float = 0.8,
                  n_requested: Optional[int] = None) -> RobustResult:
    """finalists: list of (Setpoints, WeeklyKPI, score). scenario_kpis[i]: the list
    of per-scenario WeeklyKPI for finalist i. Worst-case inlet feasibility + CVaR_alpha
    energy; ties broken by lowest CVaR energy. If no finalist is robust-feasible, fall
    back to the least-bad by CVaR energy. A finalist counts as robust-feasible only if
    it has >= ceil(n_requested/2) successful scenarios AND every successful scenario is
    feasible."""
    import math as _math
    n_scen = len(scenario_kpis[0]) if scenario_kpis else 0
    req = n_requested if n_requested is not None else n_scen
    min_ok = _math.ceil(req / 2) if req else 0
    robust_feasible = [
        bool(ks) and len(ks) >= min_ok and all(is_feasible(k, weights) for k in ks)
        for ks in scenario_kpis
    ]
    pool = [i for i, ok in enumerate(robust_feasible) if ok] or list(range(len(finalists)))

    def cvar_e(i):
        return _cvar([k.total_hvac_energy_kwh for k in scenario_kpis[i]], alpha)

    win = min(pool, key=cvar_e)
    bands = {}
    for key in ROBUST_KEYS:
        vals = [getattr(k, _RKEY_FIELD[key]) for k in scenario_kpis[win]]
        bands[key] = {"p50": _quantile(vals, 0.5), "p90": _quantile(vals, 0.9), "max": max(vals)} if vals else {}
    raw = finalists[win][3] if len(finalists[win]) > 3 else finalists[win][1]
    diagnostics = [
        {"scenario": j, "inlet_temp_max_c": scenario_kpis[win][j].inlet_temp_max,
         "feasible": is_feasible(scenario_kpis[win][j], weights)}
        for j in range(len(scenario_kpis[win]))
    ]
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=req, winner_kpi_raw=raw,
        robust_substituted=(win != 0), scenario_diagnostics=diagnostics,
        scenarios_ok=len(scenario_kpis[win]))


def make_oracle_robust_rerank(base_prototxt, oracle_config, calibration,
                              weights, n_scenarios, log_root, oracle_cls=None):
    """Build a robust_rerank_fn(finalists, forecast) -> RobustResult that evaluates
    the finalists under N perturbed-plant scenarios (each a real EnergyPlus run).
    `oracle_cls` is injectable for testing (default ParallelEnvOracle).

    Uncertainty is SINGLE-counted across the two safety layers:
    - the NOMINAL check (beam search) hedges twin-vs-plant model error with the
      k*sigma pre-tighten (cap - margin), because no degradation is physically
      modeled there;
    - a SCENARIO already physically realizes a degraded plant, so each scenario KPI
      is corrected by the MEASURED bias and then tested against the hard cap
      (inlet_forecast_margin=0 inside scenarios). Stacking the full prior margin on
      top of the realized degradation hedged the same uncertainty twice
      (e.g. cold start: a ~17-24%-degraded plant ALSO had to hold cap-1.0 C)."""
    from pathlib import Path

    if oracle_cls is None:
        from planner.oracle import ParallelEnvOracle
        oracle_cls = ParallelEnvOracle

    spread = scenario_spread(calibration)
    scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)
    scen_weights = replace(weights, inlet_forecast_margin=0.0)

    def rerank(finalists, forecast):
        setpoints = [f[0] for f in finalists]
        per_finalist = [[] for _ in finalists]
        for j, sc in enumerate(scenarios):
            sdir = str(Path(log_root) / f"scenario-{j:02d}")
            try:
                sproto = build_plant_prototxt(base_prototxt, sc, sdir)
                oracle = oracle_cls(
                    base_prototxt=sproto, project_root=".",
                    config=replace(oracle_config, log_root=str(Path(sdir) / "oracle")))
                for i, k in enumerate(oracle.evaluate(setpoints, forecast=forecast)):
                    if calibration is not None:
                        k = calibration.apply(k)   # measured bias; flags cap breach itself
                    per_finalist[i].append(k)
            except Exception:  # noqa: BLE001 - a failed scenario is dropped, never fatal
                import logging
                logging.getLogger(__name__).warning("robust scenario %d failed; dropping", j)
        return robust_select(finalists, per_finalist, scen_weights, n_requested=len(scenarios))

    return rerank
