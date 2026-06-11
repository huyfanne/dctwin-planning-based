from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from statistics import median
from typing import Any, Callable, Optional, Sequence

from planner.types import Setpoints, WeeklyKPI

# data/recirc.json — written by fit_recirc.py. Absent file = the containment default of
# scripts/recouple_ite_recirc.py (r0 = 0.10) with demand_kg_s pinned at the flow lower
# bound, which keeps the pipeline hook disengaged until the demand is actually calibrated.
RECIRC_CONFIG_PATH = "data/recirc.json"
DEFAULT_RECIRC_CONFIG = {"r0": 0.10, "demand_kg_s": 4.8, "k": 0.5}

R_MAX = 0.5          # physical clip: > 0.5 means more hot-aisle than supply air at the inlet
MIN_DELTA_T = 1.0    # deg C: |T_return - T_supply| below this degenerates the mixing identity
INLET_CAP_C = 26.0   # mirrors ObjectiveWeights.inlet_cap (the hard hall safety limit)


def load_recirc_config(path: Optional[str] = None) -> dict:
    """data/recirc.json merged over DEFAULT_RECIRC_CONFIG. An absent file or explicit
    null values fall back to the defaults, so an uncalibrated demand can never crash
    (or silently engage) the planner hook."""
    cfg = dict(DEFAULT_RECIRC_CONFIG)
    p = Path(path if path is not None else RECIRC_CONFIG_PATH)
    if p.exists():
        loaded = json.loads(p.read_text())
        cfg.update({k: v for k, v in loaded.items() if v is not None})
    return cfg


def estimate_recirc_fraction(rows: Sequence[tuple]) -> dict:
    """Fit the recirc fraction from telemetry tuples (inlet_c, supply_c, return_c[, rack]).

    Mixing identity: T_inlet = r*T_return + (1-r)*T_supply, so
    r = (T_inlet - T_supply) / (T_return - T_supply). Rows with
    |T_return - T_supply| < MIN_DELTA_T are discarded (near-zero denominator carries no
    information); each ratio is clipped to the physical [0, R_MAX] band; the estimate is
    the robust median. Returns {"r": median|None, "n": rows used, "r_per_rack": {...}}
    (per-rack medians when rows carry a 4th rack-label element).
    """
    ratios: list[float] = []
    per_rack: dict[str, list[float]] = {}
    for row in rows:
        inlet, supply, ret = float(row[0]), float(row[1]), float(row[2])
        denom = ret - supply
        if abs(denom) < MIN_DELTA_T:
            continue
        r = min(R_MAX, max(0.0, (inlet - supply) / denom))
        ratios.append(r)
        if len(row) > 3:
            per_rack.setdefault(str(row[3]), []).append(r)
    if not ratios:
        return {"r": None, "n": 0, "r_per_rack": {}}
    return {"r": float(median(ratios)), "n": len(ratios),
            "r_per_rack": {k: float(median(v)) for k, v in sorted(per_rack.items())}}


def flow_shortfall_recirc(r0: float, flow_kg_s: float, demand_kg_s: float,
                          k: float = 0.5, r_max: float = R_MAX) -> float:
    """Containment physics: recirculation rises linearly with the CRAH airflow shortfall
    vs the ITE demand — r_eff = min(r_max, r0 + k * max(0, 1 - flow/demand)). At
    flow >= demand this is exactly r0, so a calibrated demand never relaxes anything."""
    if demand_kg_s <= 0:
        return min(r_max, r0)
    shortfall = max(0.0, 1.0 - flow_kg_s / demand_kg_s)
    return min(r_max, r0 + k * shortfall)


def inlet_with_recirc(inlet_pred: float, zone_c: float, r0: float, r_eff: float) -> float:
    """Post-oracle inlet correction for recirculation above the oracle's built-in r0:
    inlet + (r_eff - r0) * max(0, zone_c - inlet). Conservative-only — the correction is
    clamped >= 0, so it can tighten safety but never relax it; r_eff == r0 is the exact
    identity (current behavior unchanged until flow undershoots demand)."""
    correction = (r_eff - r0) * max(0.0, zone_c - inlet_pred)
    return inlet_pred + max(0.0, correction)


class RecircAwareEvaluator:
    """Thin evaluator adapter: scores via the wrapped oracle, then applies the
    flow-shortfall recirc correction to each candidate's inlet KPI so the objective
    layer sees the penalty BEFORE feasibility (spec B4).

    Keeps the count/accumulator invariant documented on ObjectiveWeights: when the
    corrected inlet crosses the hard cap, inlet_violation_steps is raised to >= 1 and
    the soft excess accumulator absorbs the max-step delta — both monotone upward, so
    wrapping can only tighten safety, never weaken it. Everything else
    (evaluate_schedules, replay_with_trajectory, counters) passes through untouched.
    """

    def __init__(self, evaluator, cfg: dict, zone_c_default: float = 32.0,
                 inlet_cap_c: float = INLET_CAP_C):
        self._evaluator = evaluator
        self._cfg = dict(DEFAULT_RECIRC_CONFIG, **cfg)
        self._zone_c = zone_c_default
        self._inlet_cap = inlet_cap_c

    def evaluate(self, candidates: Sequence[Setpoints], forecast: Optional[Any] = None,
                 on_result: Optional[Callable[[], None]] = None) -> list[WeeklyKPI]:
        kpis = self._evaluator.evaluate(candidates, forecast, on_result=on_result)
        return [self._adjust(s, k) for s, k in zip(candidates, kpis)]

    def _adjust(self, s: Setpoints, kpi: WeeklyKPI) -> WeeklyKPI:
        r0 = self._cfg["r0"]
        r_eff = flow_shortfall_recirc(r0, s.flow_kg_s, self._cfg["demand_kg_s"],
                                      k=self._cfg["k"])
        adjusted = inlet_with_recirc(kpi.inlet_temp_max, self._zone_c, r0, r_eff)
        if adjusted <= kpi.inlet_temp_max:
            return kpi
        # soft excess accrues from 1 C below the cap (kpi.py / MockEvaluator convention)
        soft = self._inlet_cap - 1.0
        extra_excess = max(adjusted - soft, 0.0) - max(kpi.inlet_temp_max - soft, 0.0)
        steps = kpi.inlet_violation_steps
        if adjusted > self._inlet_cap and steps == 0:
            steps = 1
        return dataclasses.replace(
            kpi, inlet_temp_max=adjusted, inlet_violation_steps=steps,
            inlet_excess_degc_steps=kpi.inlet_excess_degc_steps + extra_excess)

    def __getattr__(self, name: str):
        return getattr(self._evaluator, name)
