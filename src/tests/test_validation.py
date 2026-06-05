from planner.validation import validation_metrics, render_report
from planner.types import WeeklyKPI


def _kpi(energy, viol=0, inlet=24.0, pue=1.2):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=pue, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True)


def test_validation_metrics():
    m = validation_metrics(ai=_kpi(80.0, viol=0, inlet=25.5), baseline=_kpi(100.0, viol=0))
    assert m["energy_reduction_pct"] == 20.0
    assert m["ai_energy_kwh"] == 80.0
    assert m["baseline_energy_kwh"] == 100.0
    assert m["ai_inlet_violations"] == 0
    assert m["passes"] is True   # reduction > 0 and 0 violations


def test_validation_fails_on_violations():
    m = validation_metrics(ai=_kpi(80.0, viol=3), baseline=_kpi(100.0))
    assert m["passes"] is False


def test_validation_fails_when_no_savings():
    m = validation_metrics(ai=_kpi(110.0, viol=0), baseline=_kpi(100.0))
    assert m["passes"] is False


def test_render_report_contains_key_numbers():
    m = validation_metrics(ai=_kpi(80.0), baseline=_kpi(100.0))
    text = render_report(m, plan_id="gds-2013-11-11")
    assert "gds-2013-11-11" in text
    assert "20.0" in text
    assert "PASS" in text
