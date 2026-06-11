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
    assert rec["schema_version"] == "1.4"
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


def test_run_weekly_plan_time_block_emits_schedule():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2, time_block=True),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)), forecaster=_FakeForecaster())
    assert rec["schema_version"] == "1.5"
    assert rec["schedule"]["cadence"] == "time-block" and len(rec["schedule"]["blocks"]) == 2


def test_run_weekly_plan_no_schedule_by_default():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)), forecaster=_FakeForecaster())
    assert "schedule" not in rec


def test_run_weekly_plan_evaluates_as_operated_baseline():
    # Given baseline_setpoints (no precomputed energy), the pipeline evaluates them
    # once and surfaces a real baseline block + energy_scope (schema 1.7).
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        baseline_setpoints=Setpoints(24.0, 9.6, 16.0),
        energy_scope="hall_controllable_v1",
    )
    assert rec["schema_version"] == "1.7"
    assert rec["energy_scope"] == "hall_controllable_v1"
    assert rec["baseline"]["source"] == "as_operated"
    assert rec["baseline"]["energy_kwh"] is not None        # was evaluated, not a placeholder
    assert rec["baseline"]["setpoints"]["crah_supply_air_temperature_c"] == 24.0
    assert rec["baseline"]["kpis"]["total_hvac_energy_kwh"] is not None  # full baseline KPI stored
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] is not None


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
    assert rec["schema_version"] == "1.4"
    assert rec["predicted_kpis_raw"]["total_hvac_energy_kwh"] == 999.0


def test_run_weekly_plan_without_robust_unchanged():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7,
                    grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
    )
    assert "robust" not in rec and rec["schema_version"] == "1.4"


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


def test_run_weekly_plan_substitutes_robust_variant_when_optimum_fragile():
    """When the energy-optimal finalists are robust-infeasible, the planner escalates to the
    safety ladder and recommends the cheapest robust-feasible variant (robust_substituted)
    instead of returning blocked_unsafe."""
    calls = []

    def fake_rerank(finalists, forecast):
        calls.append([f[0] for f in finalists])
        best = min(finalists, key=lambda f: f[2])
        if len(calls) == 1:
            # the energy-optimal beam finalists sit on the cooling cliff -> fragile
            return RobustResult(winner=best[0], winner_kpi=best[1], robust_feasible=False,
                                cvar_energy_kwh=2000.0, confidence_bands={}, n_scenarios=3,
                                winner_kpi_raw=best[1], scenarios_ok=3)
        # the margin-increasing safety-ladder variants include a robust-feasible one
        return RobustResult(winner=best[0], winner_kpi=best[1], robust_feasible=True,
                            cvar_energy_kwh=1500.0, confidence_bands={}, n_scenarios=3,
                            winner_kpi_raw=best[1], scenarios_ok=3)

    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        robust_rerank_fn=fake_rerank,
    )
    assert len(calls) == 2                            # escalated to the safety ladder
    assert rec["status"] == "pending_approval"        # a robust plan was found, not blocked
    assert rec["robust"]["robust_feasible"] is True
    assert rec["robust"]["robust_substituted"] is True


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


from planner.pipeline import apply_forecast_margin, K_SIGMA
from planner.objective import ObjectiveWeights
from planner.calibrator import Calibration, SIGMA_PRIOR


def test_apply_forecast_margin_none_calibration_is_noop():
    w = ObjectiveWeights()
    assert apply_forecast_margin(w, None) is w   # unchanged object


def test_apply_forecast_margin_cold_start_uses_prior():
    cal = Calibration.identity()                 # n_weeks == 0
    w = apply_forecast_margin(ObjectiveWeights(), cal)
    assert w.inlet_forecast_margin == K_SIGMA * SIGMA_PRIOR["inlet_temp_max_c"]


def test_apply_forecast_margin_uses_sigma_when_weeks_exist():
    cal = Calibration(bias={"inlet_temp_max_c": 2.0}, sigma={"inlet_temp_max_c": 0.4},
                      n_weeks=3, version="weeks-3")
    w = apply_forecast_margin(ObjectiveWeights(), cal)
    assert abs(w.inlet_forecast_margin - K_SIGMA * 0.4) < 1e-9


def test_apply_forecast_margin_is_idempotent():
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.4}, n_weeks=3, version="weeks-3")
    w1 = apply_forecast_margin(ObjectiveWeights(), cal)
    w2 = apply_forecast_margin(w1, cal)          # applying twice == once (sets, not adds)
    assert w2.inlet_forecast_margin == w1.inlet_forecast_margin


def test_run_weekly_plan_applies_margin_from_calibration():
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.6}, n_weeks=2, version="weeks-2")
    captured = {}
    real_planner = None
    import planner.pipeline as pp

    class _SpyPlanner(pp.BeamPlanner):
        def __init__(self, space, evaluator, weights, *args, **kwargs):
            captured["margin"] = weights.inlet_forecast_margin
            super().__init__(space, evaluator, weights, *args, **kwargs)

    orig = pp.BeamPlanner
    pp.BeamPlanner = _SpyPlanner
    try:
        run_weekly_plan(
            PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
            evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
            forecaster=_FakeForecaster(), calibration=cal)
    finally:
        pp.BeamPlanner = orig
    assert abs(captured["margin"] - K_SIGMA * 0.6) < 1e-9


def test_infeasible_fallback_is_data_driven_not_hardcoded_corner():
    """When nothing is feasible, the fallback is the safest EVALUATED coarse point (fewest
    violations, then least energy) — not the old hand-picked (sat.lb, flow.ub, chwst.lb) corner."""
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=1, grid=3, beam_width=2, levels=0),
        evaluator=MockEvaluator(MockSurface(inlet_cap=0.0, sat_opt=23.0, flow_opt=9.0, chwst_opt=16.0)),
        forecaster=_FakeForecaster())
    assert rec["status"] == "infeasible_fallback"
    sp = rec["setpoints"]
    # all candidates tie on violations -> safest_fallback picks LEAST energy -> near the bowl
    # centre (23, 9, 16), NOT the hardcoded corner (sat.lb=20, chwst.lb=13).
    assert not (sp["crah_supply_air_temperature_c"] == 20.0
                and sp["chilled_water_supply_temperature_c"] == 13.0)
    assert "degenerate_no_signal" in rec


import json


def test_run_weekly_plan_recirc_default_config_is_noop(tmp_path):
    """B4 guard: with the default recirc config (demand_kg_s == flow.lb) the recirc
    wrapper must not engage — the recommendation is identical to no config at all."""
    cfg_path = tmp_path / "recirc.json"
    cfg_path.write_text(json.dumps({"r0": 0.10, "demand_kg_s": 4.8, "k": 0.5}))
    req = dict(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2)
    rec_without = run_weekly_plan(
        PlanRequest(**req), evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(), recirc_config_path=str(tmp_path / "absent.json"))
    rec_with = run_weekly_plan(
        PlanRequest(**req), evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(), recirc_config_path=str(cfg_path))
    assert rec_with == rec_without


def test_run_weekly_plan_recirc_penalizes_low_flow(tmp_path):
    """With a calibrated ITE airflow demand (6.0 > flow.lb), low-flow candidates carry the
    recirc inlet penalty BEFORE feasibility: the fragile (sat=26, flow=4.8) energy optimum
    (inlet exactly at the 26 C cap) is pushed over the cap and rejected for a cooler plan."""
    surface = MockSurface(sat_opt=26.0, flow_opt=4.8, chwst_opt=13.0, inlet_base=20.0)
    req = dict(week_start=date(2013, 11, 11), days=1, grid=4, beam_width=3, levels=0)
    rec_plain = run_weekly_plan(
        PlanRequest(**req), evaluator=MockEvaluator(surface), forecaster=_FakeForecaster(),
        recirc_config_path=str(tmp_path / "absent.json"))
    assert rec_plain["setpoints"]["crah_supply_air_temperature_c"] == 26.0  # sits on the cap
    assert rec_plain["setpoints"]["crah_supply_air_mass_flow_rate_kg_s"] == 4.8

    cfg_path = tmp_path / "recirc.json"
    cfg_path.write_text(json.dumps({"r0": 0.10, "demand_kg_s": 6.0, "k": 0.5}))
    rec = run_weekly_plan(
        PlanRequest(**req), evaluator=MockEvaluator(surface), forecaster=_FakeForecaster(),
        recirc_config_path=str(cfg_path))
    assert rec["status"] == "pending_approval"
    sp = rec["setpoints"]
    assert sp["crah_supply_air_temperature_c"] == 24.0       # backed off the cooling cliff
    assert sp["crah_supply_air_mass_flow_rate_kg_s"] == 4.8
    # the surfaced KPI is the recirc-adjusted inlet: 24 + 0.1*(32-24) = 24.8
    assert rec["predicted_kpis"]["inlet_temp_max_c"] == pytest.approx(24.8)


def test_degenerate_no_signal_surfaced_in_recommendation():
    """A control-invariant evaluator -> the recommendation flags degenerate_no_signal + schema 1.6."""
    from planner.types import WeeklyKPI

    class FlatEvaluator:
        def evaluate(self, candidates, forecast=None, on_result=None):
            return [WeeklyKPI(total_hvac_energy_kwh=700000.0, pue_mean=1.2, inlet_temp_max=43.64,
                              inlet_violation_steps=600, rh_violation_steps=0, feasible=False)
                    for _ in candidates]

    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=1, grid=3, beam_width=2, levels=0),
        evaluator=FlatEvaluator(), forecaster=_FakeForecaster())
    assert rec["degenerate_no_signal"] is True
    assert rec["schema_version"] == "1.6"
    assert rec["status"] == "infeasible_fallback"


def test_run_weekly_plan_threads_tariff_kind_into_predicted_kpis():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        tariff_kind="carbon",
    )
    assert rec["predicted_kpis"]["tariff_kind"] == "carbon"
