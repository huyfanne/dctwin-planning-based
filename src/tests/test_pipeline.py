from datetime import date

from planner.pipeline import run_weekly_plan, PlanRequest
from planner.mock_evaluator import MockEvaluator, MockSurface


class _FakeForecaster:
    method = "persistence"
    def forecast(self, week_start, n_steps):
        class _F:
            week_start = date(2013, 11, 11)
            method = "persistence"
            def materialize(self, root): pass
        return _F()


def test_run_weekly_plan_returns_recommendation_dict():
    levels = []
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7,
                    grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        baseline_energy_kwh=200.0,
        on_level=lambda l, e, b: levels.append(l),
    )
    assert rec["schema_version"] == "1.0"
    assert rec["week_start"] == "2013-11-11"
    assert set(rec["setpoints"]) == {
        "crah_supply_air_temperature_c",
        "crah_supply_air_mass_flow_rate_kg_s",
        "chilled_water_supply_temperature_c",
    }
    assert rec["status"] == "pending_approval"
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] is not None
    assert levels  # progress callback fired


def test_run_weekly_plan_infeasible_fallback():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=1, grid=3, beam_width=2, levels=0),
        evaluator=MockEvaluator(MockSurface(inlet_cap=0.0)),  # nothing feasible
        forecaster=_FakeForecaster(),
    )
    assert rec["status"] == "infeasible_fallback"
