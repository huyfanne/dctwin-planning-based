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
    robust_feasible: Optional[bool] = None,
    cvar_energy_kwh: Optional[float] = None,
    confidence_bands: Optional[dict] = None,
    n_scenarios: Optional[int] = None,
    calibration_version: Optional[str] = None,
    raw_kpi: Optional[WeeklyKPI] = None,
    robust_substituted: bool = False,
    scenario_diagnostics: Optional[list] = None,
    scenarios_ok: Optional[int] = None,
    forecast_meta: Optional[dict] = None,
    inlet_forecast_margin: Optional[float] = None,
    k_sigma: Optional[float] = None,
    schedule=None,   # planner.schedule.WeeklySchedule
    degenerate_no_signal: bool = False,
) -> dict:
    week_end = week_start + timedelta(days=days - 1)
    reduction = (
        energy_reduction_pct(kpi.total_hvac_energy_kwh, baseline_energy_kwh)
        if baseline_energy_kwh is not None
        else None
    )
    rec = {
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
        "forecast": forecast_meta if forecast_meta is not None
                    else {"method": forecast_method, "weather": "TMY-window"},
        "search": dict(search_meta),
        "status": status,
        # True when the coarse sweep showed ~no response to the setpoints (control-invariant
        # model): the recommendation is a least-bad fallback, not a real optimum.
        "degenerate_no_signal": degenerate_no_signal,
    }
    if robust_feasible is not None:
        rec["schema_version"] = "1.1"
        rec["robust"] = {
            "robust_feasible": robust_feasible,
            "robust_substituted": robust_substituted,
            "cvar_energy_kwh": cvar_energy_kwh,
            "confidence_bands": confidence_bands or {},
            "scenario_diagnostics": scenario_diagnostics or [],
            "n_scenarios": n_scenarios,
            "scenarios_ok": scenarios_ok,
            "calibration_version": calibration_version,
        }
    if raw_kpi is not None:
        rec["predicted_kpis_raw"] = {
            "total_hvac_energy_kwh": raw_kpi.total_hvac_energy_kwh,
            "pue_mean": raw_kpi.pue_mean,
            "inlet_temp_max_c": raw_kpi.inlet_temp_max,
            "inlet_violation_steps": raw_kpi.inlet_violation_steps,
        }
        rec["schema_version"] = "1.2"
    if forecast_meta is not None:
        rec["schema_version"] = "1.3"
    if inlet_forecast_margin is not None:
        rec["inlet_forecast_margin"] = inlet_forecast_margin
        rec["k_sigma"] = k_sigma
        rec["schema_version"] = "1.4"
    if schedule is not None:
        rec["schedule"] = {
            "cadence": "time-block",
            "blocks": [
                {"label": b.label, "start_hour": b.start_hour, "end_hour": b.end_hour,
                 "setpoints": {"crah_supply_air_temperature_c": round(sp.sat_c, 2),
                               "crah_supply_air_mass_flow_rate_kg_s": round(sp.flow_kg_s, 2),
                               "chilled_water_supply_temperature_c": round(sp.chwst_c, 2)}}
                for b, sp in zip(schedule.blocks, schedule.setpoints)
            ],
        }
        rec["schema_version"] = "1.5"
    if degenerate_no_signal:
        rec["schema_version"] = "1.6"
    return rec


def write_recommendation(path: str, recommendation: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(recommendation, indent=2))
