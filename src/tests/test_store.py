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


def test_set_status(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.set_status("p1", "running")
    assert store.list_plans()[0]["status"] == "running"
