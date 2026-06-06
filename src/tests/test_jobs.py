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
