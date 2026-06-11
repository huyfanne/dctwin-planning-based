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


def deploy(recommendation_path: str, oracle, forecast=None, bms=None) -> dict:
    """Deployment: require approval, run the plant week, record realized KPIs.

    `bms` is the BMS-adapter seam (planner.bms). When given, its apply() records
    the 45 per-actuator commands under <plan_dir>/deploy/ and the rec is stamped
    deploy_mode/bms/realized_source (schema 1.8, additive). Shadow mode never
    actuates; the realized week still comes from the oracle plant run (the
    observation stand-in), so calibration keeps learning. bms=None is the
    sim-only path, byte-for-byte the pre-1.8 behavior.
    """
    rec = json.loads(Path(recommendation_path).read_text())
    if rec.get("status") != "approved":
        raise PermissionError(
            f"recommendation status is {rec.get('status')!r}; expert approval required"
        )

    setpoints = _setpoints_from_rec(rec)
    if forecast is None:
        forecast = _NullForecast(date.fromisoformat(rec["week_start"]))

    if bms is not None:
        out_dir = Path(recommendation_path).parent / "deploy"
        rec["bms"] = bms.apply(setpoints, rec["week_start"], out_dir)
        rec["deploy_mode"] = "shadow"
        rec["realized_source"] = "sim"
        rec["schema_version"] = "1.8"

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
