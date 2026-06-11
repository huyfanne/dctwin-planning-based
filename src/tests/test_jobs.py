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


def test_reconcile_orphans_fails_non_terminal_plans(tmp_path):
    # A restart loses the in-memory queue, so any plan still 'running'/'queued'/'deploying'
    # in the store is orphaned and must be marked terminal (else it shows running forever).
    from webapp.store import PlanStore
    from webapp.jobs import JobRunner
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    for pid, st in [("run", "running"), ("que", "queued"), ("dep", "deploying"),
                    ("ok", "pending_approval"), ("done", "deployed")]:
        store.create_plan(pid, "2024-11-11", {})
        store.set_status(pid, st)
    JobRunner(store).reconcile_orphans()
    assert store.get_plan_row("run")["status"] == "failed"
    assert store.get_plan_row("que")["status"] == "failed"
    assert store.get_plan_row("dep")["status"] == "deploy_failed"
    assert store.get_plan_row("ok")["status"] == "pending_approval"   # terminal untouched
    assert store.get_plan_row("done")["status"] == "deployed"         # terminal untouched


def test_start_reconciles_orphans(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import JobRunner
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("run", "2024-11-11", {}); store.set_status("run", "running")
    runner = JobRunner(store)
    runner.start()
    try:
        assert store.get_plan_row("run")["status"] == "failed"
    finally:
        runner.stop()


def test_request_cancel_stops_a_running_plan(tmp_path):
    import threading
    from unittest.mock import Mock
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    started = threading.Event()

    def looping_runner(plan_id, params, store, progress_cb):
        started.set()
        for _ in range(100000):
            progress_cb({"level": 0, "evals": 1})   # raises PlanCancelled once cancelled
            time.sleep(0.005)

    teardown = Mock()
    runner = JobRunner(store, runner=looping_runner, container_teardown=teardown)
    runner.start()
    try:
        runner.submit("p1", {})
        assert started.wait(2)
        _wait_status(store, "p1", "running")
        runner.request_cancel("p1")
        _wait_status(store, "p1", "cancelled")
        teardown.assert_called_once()       # in-flight containers torn down
    finally:
        runner.stop()


def test_request_cancel_skips_a_queued_plan(tmp_path):
    from unittest.mock import Mock
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    ran = []

    def runner_fn(plan_id, params, store, progress_cb):
        ran.append(plan_id)

    runner = JobRunner(store, runner=runner_fn, container_teardown=Mock())
    runner.request_cancel("p1")             # cancel BEFORE it is dequeued
    runner.submit("p1", {})
    # NB: start() runs reconcile_orphans first, which transiently flips the still-'queued'
    # p1 to 'failed'; the loop then dequeues it, sees the cancel flag, and sets 'cancelled'.
    # _wait_status only waits FOR 'cancelled', so the intermediate 'failed' is harmless.
    runner.start()
    try:
        _wait_status(store, "p1", "cancelled")
        time.sleep(0.2)
        assert ran == []                    # never executed
    finally:
        runner.stop()


def test_duplicate_deploy_is_skipped_and_does_not_clobber(tmp_path):
    """A stale duplicate deploy (repeat clicks while the worker was busy) must neither
    re-run deploy nor clobber the terminal 'deployed' status. (Incident
    gds-2024-11-29-729156: the deploy succeeded, then two queued duplicates re-ran,
    hit deploy()'s approval guard, and overwrote 'deployed' with 'deploy_failed'.)"""
    from webapp.jobs import JobRunner
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-29", {})
    store.save_recommendation("p1", {"plan_id": "p1", "status": "deployed",
                                     "setpoints": {}, "predicted_kpis": {}})
    store.save_realized("p1", {"total_hvac_energy_kwh": 1.0, "inlet_violation_steps": 0})
    store.set_status("p1", "deployed")
    calls = []
    runner = JobRunner(store, deploy_runner=lambda pid, st, cb: calls.append(pid))
    runner.run_deploy_sync("p1")
    assert calls == []                                          # deploy NOT re-run
    assert store.get_plan_row("p1")["status"] == "deployed"     # not clobbered


def test_duplicate_deploy_heals_a_clobbered_row(tmp_path):
    """If a duplicate already clobbered the row, the next stale duplicate restores the
    truthful terminal state from the realized KPIs (deployed, or deploy_blocked on a
    breach) instead of running deploy again."""
    from webapp.jobs import JobRunner
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    for pid, viol, expect in (("ok", 0, "deployed"), ("bad", 3, "deploy_blocked")):
        store.create_plan(pid, "2024-11-29", {})
        store.save_recommendation(pid, {"plan_id": pid, "status": "deployed",
                                        "setpoints": {}, "predicted_kpis": {}})
        store.save_realized(pid, {"total_hvac_energy_kwh": 1.0, "inlet_violation_steps": viol})
        store.set_status(pid, "deploy_failed")                  # the clobbered state
        runner = JobRunner(store, deploy_runner=lambda *_: (_ for _ in ()).throw(AssertionError))
        runner.run_deploy_sync(pid)
        assert store.get_plan_row(pid)["status"] == expect


def test_bms_adapter_for_mode_defaults_to_shadow(monkeypatch):
    # DTWIN_DEPLOY_MODE unset -> shadow is the webapp default (spec A1)
    from planner.bms import ShadowBmsAdapter
    from webapp.jobs import bms_adapter_for_mode
    monkeypatch.delenv("DTWIN_DEPLOY_MODE", raising=False)
    assert isinstance(bms_adapter_for_mode(), ShadowBmsAdapter)
    monkeypatch.setenv("DTWIN_DEPLOY_MODE", "shadow")
    assert isinstance(bms_adapter_for_mode(), ShadowBmsAdapter)


def test_bms_adapter_for_mode_sim_keeps_todays_behavior(monkeypatch):
    # 'sim' -> bms=None: deploy() takes today's exact sim-only path
    from webapp.jobs import bms_adapter_for_mode
    monkeypatch.setenv("DTWIN_DEPLOY_MODE", "sim")
    assert bms_adapter_for_mode() is None


def _hist_week(pred, real):
    return {"week_start": "2026-01-05",
            "predicted": {"total_hvac_energy_kwh": pred},
            "realized": {"total_hvac_energy_kwh": real}}


def test_write_plant_calibration_persists_proposal(tmp_path):
    import json
    from planner.calibrator import Calibration
    from webapp.jobs import write_plant_calibration
    hist = tmp_path / "calibration_history.json"
    hist.write_text(json.dumps([_hist_week(1000.0, 1100.0)] * 4))
    out = tmp_path / "plant_calibration.json"
    prop = write_plant_calibration(Calibration.identity(), str(hist), str(out))
    assert prop is not None and out.exists()
    data = json.loads(out.read_text())
    [p] = data["perturbations"]
    assert p["table"] == "Fan_VariableVolume"
    assert p["field"] == "fan_total_efficiency"
    assert abs(p["factor"] - 1 / 1.1) < 1e-9
    assert data["basis"]["n_weeks"] == 4


def test_write_plant_calibration_no_proposal_writes_nothing(tmp_path):
    import json
    from planner.calibrator import Calibration
    from webapp.jobs import write_plant_calibration
    hist = tmp_path / "calibration_history.json"
    hist.write_text(json.dumps([_hist_week(1000.0, 1100.0)] * 2))   # below min_weeks
    out = tmp_path / "plant_calibration.json"
    assert write_plant_calibration(Calibration.identity(), str(hist), str(out)) is None
    assert not out.exists()
    # an absent history file is fine too (cold start)
    assert write_plant_calibration(Calibration.identity(),
                                   str(tmp_path / "missing.json"), str(out)) is None
    assert not out.exists()


def test_write_plant_calibration_is_guarded_never_raises(tmp_path):
    # The deploy-loop write must NEVER fail the deploy: malformed history (and even a
    # None calibration) -> None, no exception, no file.
    from webapp.jobs import write_plant_calibration
    hist = tmp_path / "calibration_history.json"
    hist.write_text("{definitely not json")
    out = tmp_path / "plant_calibration.json"
    assert write_plant_calibration(None, str(hist), str(out)) is None
    assert not out.exists()


def test_plan_params_n_scenarios_default_and_bounds():
    import pytest
    from pydantic import ValidationError
    from webapp.schemas import PlanParams
    p = PlanParams(week_start="2013-11-11")
    assert p.n_scenarios == 4
    # jobs.run_plan_job reads params.get("n_scenarios", 4) from the dumped dict
    assert p.model_dump()["n_scenarios"] == 4
    assert PlanParams(week_start="2013-11-11", n_scenarios=2).n_scenarios == 2
    assert PlanParams(week_start="2013-11-11", n_scenarios=8).n_scenarios == 8
    with pytest.raises(ValidationError):
        PlanParams(week_start="2013-11-11", n_scenarios=1)
    with pytest.raises(ValidationError):
        PlanParams(week_start="2013-11-11", n_scenarios=9)


def test_deploy_failure_does_not_downgrade_terminal_status(tmp_path):
    """If the runner reached 'deployed' before raising, the failure handler must not
    downgrade the terminal state."""
    from webapp.jobs import JobRunner
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-29", {})
    store.save_recommendation("p1", {"plan_id": "p1", "status": "approved",
                                     "setpoints": {}, "predicted_kpis": {}})

    def runner_sets_deployed_then_raises(pid, st, cb):
        st.set_status(pid, "deployed")
        raise RuntimeError("post-deploy hiccup")

    runner = JobRunner(store, deploy_runner=runner_sets_deployed_then_raises)
    runner.run_deploy_sync("p1")
    assert store.get_plan_row("p1")["status"] == "deployed"
