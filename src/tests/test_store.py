from datetime import date

from webapp.store import PlanStore


def test_create_list_and_get(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={"days": 7})
    assert (tmp_path / "runs" / "p1").is_dir()

    summaries = store.list_plans()
    assert len(summaries) == 1
    assert summaries[0]["plan_id"] == "p1"
    assert summaries[0]["status"] == "queued"


def test_save_recommendation_updates_index(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    rec = {
        "status": "pending_approval",
        "predicted_kpis": {"total_hvac_energy_kwh": 80.0,
                           "energy_reduction_vs_baseline_pct": 20.0},
        "setpoints": {"crah_supply_air_temperature_c": 24.0},
    }
    store.save_recommendation("p1", rec)
    got = store.get_recommendation("p1")
    assert got["setpoints"]["crah_supply_air_temperature_c"] == 24.0
    s = store.list_plans()[0]
    assert s["status"] == "pending_approval"
    assert s["energy_kwh"] == 80.0
    assert s["reduction_pct"] == 20.0


def test_progress_roundtrip(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.write_progress("p1", {"level": 1, "evals": 50, "best_score": 123.4})
    assert store.read_progress("p1")["evals"] == 50


def test_progress_sanitizes_non_finite(tmp_path):
    # all-infeasible search -> best_score = +inf; must store as null (valid JSON,
    # not "Infinity") so the API response doesn't 500.
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.write_progress("p1", {"level": 0, "evals": 8, "best_score": float("inf")})
    got = store.read_progress("p1")
    assert got["best_score"] is None
    assert got["evals"] == 8
    raw = (tmp_path / "runs" / "p1" / "progress.json").read_text()
    assert "Infinity" not in raw


def test_set_status(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.set_status("p1", "running")
    assert store.list_plans()[0]["status"] == "running"


def test_realized_roundtrip(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    assert store.get_realized("p1") is None
    realized = {"total_hvac_energy_kwh": 30000.0, "inlet_temp_max_c": 26.4,
                "pue_mean": 1.2, "inlet_violation_steps": 3}
    store.save_realized("p1", realized)
    got = store.get_realized("p1")
    assert got["inlet_temp_max_c"] == 26.4


def test_get_trajectory_parses_two_csvs(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    pdir = store.plan_dir("p1") / "prevalidation"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "trajectory_ai.csv").write_text("step,inlet_temp_max_c,hvac_power_kw,pue\n0,24.0,0.2,1.2\n")
    (pdir / "trajectory_worst.csv").write_text("step,inlet_temp_max_c,hvac_power_kw,pue\n0,28.0,0.5,1.3\n")
    traj = store.get_trajectory("p1")
    assert traj["nominal"][0]["inlet_temp_max_c"] == 24.0
    assert traj["worst"][0]["inlet_temp_max_c"] == 28.0


def test_get_trajectory_missing_is_empty(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.plan_dir("p2")
    assert store.get_trajectory("p2") == {"nominal": [], "worst": []}
