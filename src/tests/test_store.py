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


def test_save_realized_records_energy_in_index(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2013-11-11", {})
    store.save_realized("p1", {"total_hvac_energy_kwh": 31000.0, "inlet_violation_steps": 0})
    row = store.get_plan_row("p1")
    assert row["realized_energy_kwh"] == 31000.0
    assert any(p["plan_id"] == "p1" and p["realized_energy_kwh"] == 31000.0
               for p in store.list_plans())


def test_read_progress_tolerates_empty_or_partial_file(tmp_path):
    # The exact SSE crash: a reader catches progress.json mid-write (empty/partial JSON).
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p", "2024-11-11", {})
    pj = store.plan_dir("p") / "progress.json"
    pj.write_text("")                 # empty (truncated mid-write)
    assert store.read_progress("p") == {}
    pj.write_text('{"level": 1, ')    # partial JSON
    assert store.read_progress("p") == {}


def test_write_then_read_progress_roundtrips(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p", "2024-11-11", {})
    store.write_progress("p", {"level": 2, "evals": 9, "best_score": 1.5})
    assert store.read_progress("p") == {"level": 2, "evals": 9, "best_score": 1.5}


def test_write_progress_atomic_under_concurrent_reads(tmp_path):
    # Reproduce the race: write progress in a tight loop while reading it. With a
    # non-atomic write + unguarded read this raises JSONDecodeError; the fix must not.
    import threading
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p", "2024-11-11", {})
    errors, stop = [], threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            store.write_progress("p", {"level": i % 4, "evals": i, "best_score": 0.5})
            i += 1

    t = threading.Thread(target=writer); t.start()
    try:
        for _ in range(3000):
            store.read_progress("p")          # must never raise
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))
    finally:
        stop.set(); t.join(timeout=2)
    assert errors == []


def test_get_recommendation_tolerates_partial_file(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p", "2024-11-11", {})
    (store.plan_dir("p") / "recommendation.json").write_text("")   # empty/mid-write
    assert store.get_recommendation("p") is None


def test_delete_plan_removes_row_and_dir(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    assert (tmp_path / "runs" / "p1").is_dir()
    store.delete_plan("p1")
    assert not (tmp_path / "runs" / "p1").exists()       # run dir removed
    assert store.get_plan_row("p1") is None              # index row removed
    assert store.list_plans() == []
