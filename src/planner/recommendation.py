from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Sequence

from planner.types import Setpoints, WeeklyKPI


def energy_reduction_pct(plan_kwh: float, baseline_kwh: float) -> float:
    if not baseline_kwh:
        return 0.0
    return (baseline_kwh - plan_kwh) / baseline_kwh * 100.0


def safest_fallback(kpis: Sequence[WeeklyKPI]) -> int:
    """Index of the safest candidate: fewest inlet violations, then least energy."""
    return min(
        range(len(kpis)),
        key=lambda i: (kpis[i].inlet_violation_steps, kpis[i].total_hvac_energy_kwh),
    )


def build_recommendation(
    setpoints: Setpoints,
    kpi: WeeklyKPI,
    week_start: date,
    days: int,
    forecast_method: str,
    search_meta: dict,
    baseline_energy_kwh: Optional[float] = None,
    status: str = "pending_approval",
) -> dict:
    week_end = week_start + timedelta(days=days - 1)
    reduction = (
        energy_reduction_pct(kpi.total_hvac_energy_kwh, baseline_energy_kwh)
        if baseline_energy_kwh is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "plan_id": f"gds-{week_start.isoformat()}",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "cadence": "weekly",
        "setpoints": {
            "crah_supply_air_temperature_c": round(setpoints.sat_c, 2),
            "crah_supply_air_mass_flow_rate_kg_s": round(setpoints.flow_kg_s, 2),
            "chilled_water_supply_temperature_c": round(setpoints.chwst_c, 2),
        },
        "predicted_kpis": {
            "total_hvac_energy_kwh": kpi.total_hvac_energy_kwh,
            "pue_mean": kpi.pue_mean,
            "inlet_temp_max_c": kpi.inlet_temp_max,
            "inlet_violation_steps": kpi.inlet_violation_steps,
            "energy_reduction_vs_baseline_pct": reduction,
        },
        "forecast": {"method": forecast_method, "weather": "TMY-window"},
        "search": dict(search_meta),
        "status": status,
    }


def write_recommendation(path: str, recommendation: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(recommendation, indent=2))
