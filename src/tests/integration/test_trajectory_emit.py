"""Docker-gated: a real plan emits both trajectory CSVs and GET /trajectory serves them.
Run: env -C src sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
  tests/integration/test_trajectory_emit.py -m integration -v"
"""
import pytest

pytestmark = pytest.mark.integration


def test_prevalidation_emits_both_trajectories(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    plan_id = "gds-traj-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2}
    store.create_plan(plan_id, params["week_start"], params)
    run_plan_job(plan_id, params, store, lambda p: None)
    # NOTE: week_start "2013-11-11" assumes models/forecaster.pkl has weather_file=None
    # (TMY) — the state until the Final-Verification real-EPW regen. If the pkl carries the
    # real Nov2024-Jan2025 EPW, use a within-coverage week (e.g. "2024-11-11") instead.

    traj = store.get_trajectory(plan_id)
    assert len(traj["nominal"]) > 0, "nominal trajectory CSV not emitted"
    assert len(traj["worst"]) > 0, "worst-case trajectory CSV not emitted"
    # the worst-case scenario should run at least as hot as nominal
    nmax = max(r["inlet_temp_max_c"] for r in traj["nominal"] if r["inlet_temp_max_c"] is not None)
    wmax = max(r["inlet_temp_max_c"] for r in traj["worst"] if r["inlet_temp_max_c"] is not None)
    assert wmax >= nmax - 0.5
