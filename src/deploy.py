from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from planner.types import Setpoints


def _setpoints_from_rec(rec: dict) -> Setpoints:
    s = rec["setpoints"]
    return Setpoints(
        sat_c=s["crah_supply_air_temperature_c"],
        flow_kg_s=s["crah_supply_air_mass_flow_rate_kg_s"],
        chwst_c=s["chilled_water_supply_temperature_c"],
    )


class _NullForecast:
    """Forecast token for deploy: workloads already materialized; carry week_start."""
    def __init__(self, week_start: date):
        self.week_start = week_start
    def materialize(self, project_root):  # already on disk from planning
        pass


def deploy(recommendation_path: str, oracle, forecast=None) -> dict:
    """Sim-only deployment: require approval, run the plant week, record realized KPIs.

    The physical-BMS adapter is intentionally a stub here (sim-only ground truth).
    To target a real BMS later, implement a `BmsAdapter.apply(setpoints, week)` and
    call it in place of the oracle plant-run below; the contract is the same dict.
    """
    rec = json.loads(Path(recommendation_path).read_text())
    if rec.get("status") != "approved":
        raise PermissionError(
            f"recommendation status is {rec.get('status')!r}; expert approval required"
        )

    setpoints = _setpoints_from_rec(rec)
    if forecast is None:
        forecast = _NullForecast(date.fromisoformat(rec["week_start"]))

    realized = oracle.evaluate([setpoints], forecast=forecast)[0]
    rec["realized_kpis"] = {
        "total_hvac_energy_kwh": realized.total_hvac_energy_kwh,
        "pue_mean": realized.pue_mean,
        "inlet_temp_max_c": realized.inlet_temp_max,
        "inlet_violation_steps": realized.inlet_violation_steps,
    }
    rec["status"] = "deployed"
    Path(recommendation_path).write_text(json.dumps(rec, indent=2))
    return rec
