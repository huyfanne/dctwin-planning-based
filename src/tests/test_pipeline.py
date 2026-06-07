from datetime import date

from planner.pipeline import run_weekly_plan, PlanRequest
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.robust import RobustResult
from planner.types import Setpoints, WeeklyKPI


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
    assert rec["schema_version"] == "1.3"
    assert rec["forecast"] == {"method": "persistence", "weather": "TMY-window", "bands": False}
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


def test_run_weekly_plan_applies_robust_rerank():
    chosen = Setpoints(21.0, 12.0, 14.0)
    chosen_kpi = WeeklyKPI(total_hvac_energy_kwh=999.0, pue_mean=1.1, inlet_temp_max=25.0,
                           inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                           inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)

    def fake_rerank(finalists, forecast):
        return RobustResult(winner=chosen, winner_kpi=chosen_kpi, robust_feasible=True,
                            cvar_energy_kwh=1010.0,
                            confidence_bands={"inlet_temp_max_c": {"p50": 25.0, "p90": 25.5, "max": 26.0}},
                            n_scenarios=3)

    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7,
                    grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        robust_rerank_fn=fake_rerank,
    )
    assert rec["setpoints"]["crah_supply_air_temperature_c"] == 21.0
    assert rec["robust"]["robust_feasible"] is True
    assert rec["robust"]["cvar_energy_kwh"] == 1010.0
    assert rec["schema_version"] == "1.3"
    assert rec["predicted_kpis_raw"]["total_hvac_energy_kwh"] == 999.0


def test_run_weekly_plan_without_robust_unchanged():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7,
                    grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
    )
    assert "robust" not in rec and rec["schema_version"] == "1.3"


def test_run_weekly_plan_blocks_when_not_robust_feasible():
    chosen = Setpoints(21.0, 12.0, 14.0)
    chosen_kpi = WeeklyKPI(total_hvac_energy_kwh=999.0, pue_mean=1.1, inlet_temp_max=27.0,
                           inlet_violation_steps=5, rh_violation_steps=0, feasible=False,
                           inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)

    def fake_rerank(finalists, forecast):
        return RobustResult(winner=chosen, winner_kpi=chosen_kpi, robust_feasible=False,
                            cvar_energy_kwh=2000.0,
                            confidence_bands={"inlet_temp_max_c": {"p50": 26.5, "p90": 27.5, "max": 28.0}},
                            n_scenarios=3)

    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        robust_rerank_fn=fake_rerank,
    )
    assert rec["status"] == "blocked_unsafe"
    assert rec["robust"]["robust_feasible"] is False
    # the robust winner (least-bad finalist) is still surfaced, not the coolest-corner fallback
    assert rec["setpoints"]["crah_supply_air_temperature_c"] == 21.0


import pytest
from planner.pipeline import validate_plan_request, PlanRequest
from planner.beam_search import BeamConfig
from planner.objective import ObjectiveWeights


def test_validate_plan_request_accepts_defaults():
    validate_plan_request(PlanRequest(week_start=date(2013, 11, 11)),
                          ObjectiveWeights(), BeamConfig())  # no raise


@pytest.mark.parametrize("beam,weights,days,msg", [
    (BeamConfig(grid=1), ObjectiveWeights(), 7, "grid"),
    (BeamConfig(beam_width=0), ObjectiveWeights(), 7, "beam_width"),
    (BeamConfig(levels=-1), ObjectiveWeights(), 7, "levels"),
    (BeamConfig(max_evals=0), ObjectiveWeights(), 7, "max_evals"),
    (BeamConfig(), ObjectiveWeights(lambda_temp=-1.0), 7, "weight"),
    (BeamConfig(), ObjectiveWeights(), 0, "days"),
])
def test_validate_plan_request_rejects(beam, weights, days, msg):
    with pytest.raises(ValueError, match=msg):
        validate_plan_request(PlanRequest(week_start=date(2013, 11, 11), days=days), weights, beam)
