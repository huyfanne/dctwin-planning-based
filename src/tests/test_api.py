import uuid

import pytest
from fastapi.testclient import TestClient

from webapp.main import create_app
from webapp.auth import TokenAuth
from webapp.store import PlanStore


@pytest.fixture
def client(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    auth = TokenAuth({"op": "operator", "ex": "expert"})

    # synchronous fake runner so the plan completes immediately
    def fake_runner(plan_id, params, store, progress_cb):
        progress_cb({"level": 0, "evals": 5, "best_score": 1.0})
        store.save_recommendation(plan_id, {
            "status": "pending_approval",
            "setpoints": {"crah_supply_air_temperature_c": 24.0,
                          "crah_supply_air_mass_flow_rate_kg_s": 6.2,
                          "chilled_water_supply_temperature_c": 18.0},
            "predicted_kpis": {"total_hvac_energy_kwh": 80.0,
                               "energy_reduction_vs_baseline_pct": 20.0},
        })

    app = create_app(store=store, auth=auth, runner=fake_runner, run_sync=True)
    return TestClient(app)


def _op():
    return {"Authorization": "Bearer op"}


def _ex():
    return {"Authorization": "Bearer ex"}


def test_create_requires_auth(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11"})
    assert r.status_code == 401


def test_operator_creates_plan_and_it_completes(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op())
    assert r.status_code == 202
    plan_id = r.json()["plan_id"]

    detail = client.get(f"/api/plans/{plan_id}", headers=_op()).json()
    assert detail["status"] == "pending_approval"
    assert detail["recommendation"]["setpoints"]["crah_supply_air_temperature_c"] == 24.0

    listed = client.get("/api/plans", headers=_op()).json()
    assert any(p["plan_id"] == plan_id for p in listed)

    prog = client.get(f"/api/plans/{plan_id}/progress", headers=_op()).json()
    assert prog["evals"] == 5


def test_operator_cannot_approve(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.post(f"/api/plans/{plan_id}/approve", headers=_op())
    assert r.status_code == 403


def test_expert_can_approve(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.post(f"/api/plans/{plan_id}/approve", headers=_ex())
    assert r.status_code == 200
    assert client.get(f"/api/plans/{plan_id}", headers=_ex()).json()["status"] == "approved"


def test_expert_can_edit_setpoints(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.patch(f"/api/plans/{plan_id}/setpoints",
                     json={"crah_supply_air_temperature_c": 25.0,
                           "crah_supply_air_mass_flow_rate_kg_s": 7.0,
                           "chilled_water_supply_temperature_c": 17.0},
                     headers=_ex())
    assert r.status_code == 200
    sp = client.get(f"/api/plans/{plan_id}", headers=_ex()).json()["recommendation"]["setpoints"]
    assert sp["crah_supply_air_temperature_c"] == 25.0


def test_topology_returns_22_crahs(client):
    r = client.get("/api/topology", headers=_op())
    assert r.status_code == 200
    topo = r.json()
    assert len(topo["crahs"]) == 22


def _deploy_client(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    auth = TokenAuth({"op": "operator", "ex": "expert"})

    def fake_deploy(plan_id, store_, progress_cb):
        store_.save_realized(plan_id, {"total_hvac_energy_kwh": 30000.0,
                                       "inlet_temp_max_c": 26.2, "pue_mean": 1.2,
                                       "inlet_violation_steps": 1})
        store_.set_status(plan_id, "deployed")

    app = create_app(store=store, auth=auth, run_sync=True, deploy_runner=fake_deploy)
    return TestClient(app), store


def test_deploy_requires_expert_and_approval(tmp_path):
    client, store = _deploy_client(tmp_path)
    store.create_plan("p1", "2013-11-11", {})
    store.save_recommendation("p1", {"plan_id": "p1", "week_start": "2013-11-11",
                                     "status": "pending_approval", "setpoints": {}})
    assert client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer op"}).status_code == 403
    assert client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer ex"}).status_code == 409
    client.post("/api/plans/p1/approve", headers={"Authorization": "Bearer ex"})
    r = client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer ex"})
    assert r.status_code == 202
    got = client.get("/api/plans/p1", headers={"Authorization": "Bearer op"}).json()
    assert got["status"] == "deployed"
    assert got["realized"]["inlet_temp_max_c"] == 26.2
