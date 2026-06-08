import time

from webapp.jobs import JobRunner
from webapp.store import PlanStore


def _make(tmp_path):
    return PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))


def test_job_runs_and_sets_status(tmp_path):
    store = _make(tmp_path)
    store.create_plan("p1", "2013-11-11", {})

    def fake_runner(plan_id, params, store, progress_cb):
        progress_cb({"level": 0, "evals": 10, "best_score": 1.0})
        store.save_recommendation(plan_id, {"status": "pending_approval",
                                            "predicted_kpis": {}, "setpoints": {}})

    runner = JobRunner(store, runner=fake_runner)
    runner.start()
    try:
        runner.submit("p1", {})
        _wait_status(store, "p1", "pending_approval")
    finally:
        runner.stop()

    assert store.list_plans()[0]["status"] == "pending_approval"
    assert store.read_progress("p1")["evals"] == 10


def test_job_failure_sets_failed(tmp_path):
    store = _make(tmp_path)
    store.create_plan("p2", "2013-11-11", {})

    def boom(plan_id, params, store, progress_cb):
        raise RuntimeError("kaboom")

    runner = JobRunner(store, runner=boom)
    runner.start()
    try:
        runner.submit("p2", {})
        _wait_status(store, "p2", "failed")
    finally:
        runner.stop()

    assert store.list_plans()[0]["status"] == "failed"


def _wait_status(store, plan_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = store.get_plan_row(plan_id)
        if row and row["status"] == target:
            return
        time.sleep(0.05)
    raise AssertionError(f"{plan_id} did not reach {target}")


def test_jobrunner_dispatches_deploy(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.set_status("p1", "approved")
    calls = []

    def fake_deploy(plan_id, store_, progress_cb):
        calls.append(plan_id)
        store_.set_status(plan_id, "deployed")

    runner = JobRunner(store, deploy_runner=fake_deploy)
    runner.run_deploy_sync("p1")
    assert calls == ["p1"]
    assert store.get_plan_row("p1")["status"] == "deployed"


def test_deploy_helpers_produce_calibration(tmp_path):
    from datetime import date
    from planner.history import advance_calibration
    from planner.calibrator import recompute_calibration, load_calibration

    hist = str(tmp_path / "calibration_history.json")
    cal_out = str(tmp_path / "calibration.json")
    predicted = {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    realized = {"total_hvac_energy_kwh": 106.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    advance_calibration(predicted, realized, date(2013, 11, 11), hist)
    cal = recompute_calibration(hist, cal_out)
    assert cal.bias["total_hvac_energy_kwh"] == 6.0
    assert load_calibration(cal_out).n_weeks == 1


def test_robust_rerank_fn_composes(tmp_path, monkeypatch):
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank, RobustResult
    from planner.types import Setpoints, WeeklyKPI
    from planner.objective import ObjectiveWeights

    from planner.oracle import OracleConfig
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass
        def evaluate(self, candidates, forecast=None, on_result=None):
            return [WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                              inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                              inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0,
                              zone_temp_band_steps=0.0) for _ in candidates]

    sp = Setpoints(24, 8, 17)
    nominal = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                        inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                        inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt",
                                   OracleConfig(n_workers=1, timesteps_per_hour=4, log_root=str(tmp_path)),
                                   None, ObjectiveWeights(), 2, str(tmp_path), oracle_cls=_Oracle)
    rr = fn([(sp, nominal, 100.0)], forecast=None)
    assert isinstance(rr, RobustResult) and rr.n_scenarios == 2


def test_deploy_status_blocked_on_realized_breach(tmp_path):
    from webapp.jobs import deploy_status_for
    # a realized week with inlet violations must NOT be marked 'deployed'
    assert deploy_status_for({"inlet_violation_steps": 666}) == "deploy_blocked"
    assert deploy_status_for({"inlet_violation_steps": 0}) == "deployed"
    assert deploy_status_for({}) == "deployed"  # missing key -> treat as no recorded breach


def test_residual_source_prefers_raw_predicted():
    from webapp.jobs import residual_predicted_for
    rec = {"predicted_kpis": {"inlet_temp_max_c": 27.0},        # calibrated (already +2)
           "predicted_kpis_raw": {"inlet_temp_max_c": 25.0}}    # raw
    assert residual_predicted_for(rec) == {"inlet_temp_max_c": 25.0}
    # backward-compat: old recs without raw fall back to predicted_kpis
    assert residual_predicted_for({"predicted_kpis": {"inlet_temp_max_c": 25.0}}) == {"inlet_temp_max_c": 25.0}


def test_robust_rerank_weights_carry_the_margin():
    from webapp.jobs import robust_weights_for
    from planner.calibrator import Calibration, SIGMA_PRIOR
    from planner.pipeline import K_SIGMA
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.5}, n_weeks=2, version="weeks-2")
    w = robust_weights_for(cal)
    assert abs(w.inlet_forecast_margin - K_SIGMA * 0.5) < 1e-9
    # cold start uses the prior
    w0 = robust_weights_for(Calibration.identity())
    assert w0.inlet_forecast_margin == K_SIGMA * SIGMA_PRIOR["inlet_temp_max_c"]


def test_record_failure_stores_reason_and_status(tmp_path):
    from webapp.jobs import record_failure
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    record_failure(store, "p1", ValueError("boom"))
    assert store.read_progress("p1") == {"error": "boom"}
    assert store.get_plan_row("p1")["status"] == "failed"


def test_record_failure_falls_back_to_class_name(tmp_path):
    from webapp.jobs import record_failure
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p2", "2024-11-11", {})
    record_failure(store, "p2", RuntimeError())          # str(exc) == ""
    assert store.read_progress("p2") == {"error": "RuntimeError"}
