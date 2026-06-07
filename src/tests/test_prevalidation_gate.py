import json

from prevalidation import set_status


def test_set_status_approves(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "approved")
    assert json.loads(p.read_text())["status"] == "approved"


def test_set_status_reject(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "rejected")
    assert json.loads(p.read_text())["status"] == "rejected"


def test_run_prevalidation_independent_replay_emits_artifacts(tmp_path, monkeypatch):
    import json
    from datetime import date
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from planner.mock_evaluator import MockEvaluator, MockSurface
    import prevalidation

    # a recommendation whose stored predicted_kpis are deliberately WRONG; the
    # independent replay must recompute, not echo them.
    bad_kpi = WeeklyKPI(total_hvac_energy_kwh=1.0, pue_mean=1.0, inlet_temp_max=0.0,
                        inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(setpoints=Setpoints(22.0, 7.0, 15.0), kpi=bad_kpi,
                               week_start=date(2013, 11, 11), days=1, forecast_method="persistence",
                               search_meta={"evals": 1})
    rec_path = tmp_path / "recommendation.json"
    rec_path.write_text(json.dumps(rec))

    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    metrics = prevalidation.run_prevalidation(
        str(rec_path), evaluator=ev, baseline=Setpoints(24.0, 13.8, 13.0),
        out_dir=str(tmp_path))

    # the replay produced its OWN ai KPIs (not the bogus 1.0 stored energy).
    # validation_metrics returns FLAT keys: ai_energy_kwh, baseline_energy_kwh,
    # energy_reduction_pct, ai_pue_mean, baseline_pue_mean, ai_inlet_max_c,
    # ai_inlet_violations, passes (see planner/validation.py).
    assert metrics["ai_energy_kwh"] != 1.0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "trajectory_ai.csv").exists()
