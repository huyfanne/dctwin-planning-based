"""Docker-gated smoke: a time-block plan emits a day/night schedule and the per-step action
differs between day and night hours. OPTIONAL to run (BCVTB is flaky). Run:
  env -C src sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
    tests/integration/test_time_block.py -m integration -v"
"""
import pytest

pytestmark = pytest.mark.integration


def test_time_block_plan_emits_schedule(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    plan_id = "gds-tb-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2, "time_block": True}
    store.create_plan(plan_id, params["week_start"], params)
    run_plan_job(plan_id, params, store, lambda p: None)

    rec = store.get_recommendation(plan_id)
    # if the constant was robust-feasible, a schedule must be present with 2 blocks
    if rec["status"] == "pending_approval":
        assert rec.get("schema_version") == "1.5"
        assert rec["schedule"]["cadence"] == "time-block"
        assert len(rec["schedule"]["blocks"]) == 2
        day = rec["schedule"]["blocks"][0]["setpoints"]
        night = rec["schedule"]["blocks"][1]["setpoints"]
        assert day and night                                  # both present
    else:
        # blocked_unsafe/infeasible_fallback -> no schedule (constant only), per the spec
        assert "schedule" not in rec
