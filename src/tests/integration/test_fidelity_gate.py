"""Docker-gated regression: the demonstrated 666-violation deployment cannot ship.
A plan that breaches on the perturbed plant must end either gated (blocked_unsafe /
deploy_blocked) or with a realized 0-violation deploy. Run:
  cd src && sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
    tests/integration/test_fidelity_gate.py -m integration -v"
"""
import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_breaching_plan_cannot_ship(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job, run_deploy_job, deploy_status_for
    from webapp.status import PlanStatus

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    plan_id = "gds-accept-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2}
    store.create_plan(plan_id, params["week_start"], params)

    run_plan_job(plan_id, params, store, lambda p: None)
    rec = store.get_recommendation(plan_id)

    if rec["status"] in (PlanStatus.BLOCKED_UNSAFE, PlanStatus.INFEASIBLE_FALLBACK):
        return  # gated at plan time — safe, breach cannot reach approval

    # otherwise it reached pending_approval: approve + deploy, assert the backstop holds
    rec["status"] = PlanStatus.APPROVED
    store.save_recommendation(plan_id, rec)
    store.set_status(plan_id, PlanStatus.APPROVED)
    store.set_status(plan_id, PlanStatus.DEPLOYING)
    run_deploy_job(plan_id, store, lambda p: None)

    realized = store.get_realized(plan_id)
    final = store.get_plan_row(plan_id)["status"]
    # EITHER the realized week is clean, OR the backstop blocked it — never silently 'deployed' with a breach
    assert final == deploy_status_for(realized)
    if realized["inlet_violation_steps"] > 0:
        assert final == PlanStatus.DEPLOY_BLOCKED
    else:
        assert final == PlanStatus.DEPLOYED
