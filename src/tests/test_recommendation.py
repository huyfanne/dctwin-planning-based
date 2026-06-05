import json
from datetime import date

from planner.recommendation import (
    build_recommendation, write_recommendation, safest_fallback, energy_reduction_pct,
)
from planner.types import Setpoints, WeeklyKPI


def _kpi(energy, viol=0, inlet=24.0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True)


def test_energy_reduction_pct():
    assert energy_reduction_pct(plan_kwh=80.0, baseline_kwh=100.0) == 20.0
    assert energy_reduction_pct(plan_kwh=100.0, baseline_kwh=0.0) == 0.0


def test_safest_fallback_prefers_fewest_violations_then_energy():
    kpis = [_kpi(50.0, viol=5), _kpi(90.0, viol=0), _kpi(70.0, viol=0)]
    assert safest_fallback(kpis) == 2   # 0 violations, lowest energy among those


def test_build_recommendation_schema():
    rec = build_recommendation(
        setpoints=Setpoints(24.0, 6.2, 18.0),
        kpi=_kpi(80.0),
        week_start=date(2013, 11, 11), days=7,
        forecast_method="persistence",
        search_meta={"evals": 245, "beam_width": 5, "levels": 3},
        baseline_energy_kwh=100.0,
        status="pending_approval",
    )
    assert rec["schema_version"] == "1.0"
    assert rec["week_start"] == "2013-11-11"
    assert rec["week_end"] == "2013-11-17"
    assert rec["setpoints"] == {
        "crah_supply_air_temperature_c": 24.0,
        "crah_supply_air_mass_flow_rate_kg_s": 6.2,
        "chilled_water_supply_temperature_c": 18.0,
    }
    assert rec["predicted_kpis"]["total_hvac_energy_kwh"] == 80.0
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] == 20.0
    assert rec["search"]["evals"] == 245
    assert rec["status"] == "pending_approval"


def test_build_recommendation_without_baseline_sets_null_reduction():
    rec = build_recommendation(Setpoints(24.0, 6.2, 18.0), _kpi(80.0),
                               date(2013, 11, 11), 7, "persistence",
                               {"evals": 1, "beam_width": 1, "levels": 0},
                               baseline_energy_kwh=None, status="pending_approval")
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] is None


def test_write_and_read_roundtrip(tmp_path):
    rec = build_recommendation(Setpoints(24.0, 6.2, 18.0), _kpi(80.0),
                               date(2013, 11, 11), 7, "persistence",
                               {"evals": 1, "beam_width": 1, "levels": 0},
                               baseline_energy_kwh=100.0, status="pending_approval")
    p = tmp_path / "recommendation.json"
    write_recommendation(str(p), rec)
    assert json.loads(p.read_text())["setpoints"]["crah_supply_air_temperature_c"] == 24.0
