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


def test_get_calibration(tmp_path, monkeypatch):
    from webapp.main import create_app
    from webapp.auth import TokenAuth
    from webapp.store import PlanStore
    from fastapi.testclient import TestClient
    from planner.calibrator import Calibration, save_calibration

    monkeypatch.chdir(tmp_path)                       # isolate data/ writes
    save_calibration(Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                                 n_weeks=2, version="weeks-2"), "data/calibration.json")
    store = PlanStore(runs_dir="runs", db_path="index.db")
    app = create_app(store=store, auth=TokenAuth({"op": "operator"}), run_sync=True)
    client = TestClient(app)
    r = client.get("/api/calibration", headers={"Authorization": "Bearer op"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_weeks"] == 2
    assert body["bias"]["inlet_temp_max_c"] == 1.0


_SP = {"crah_supply_air_temperature_c": 22.0,
       "crah_supply_air_mass_flow_rate_kg_s": 7.0,
       "chilled_water_supply_temperature_c": 15.0}


def test_patch_setpoints_rejected_after_approval(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"},
                      headers=_op()).json()["plan_id"]
    client.post(f"/api/plans/{pid}/approve", headers=_ex())          # -> approved
    r = client.patch(f"/api/plans/{pid}/setpoints", json=_SP, headers=_ex())
    assert r.status_code == 409


def test_patch_setpoints_invalidates_kpis_and_blocks_approval(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"},
                      headers=_op()).json()["plan_id"]
    client.patch(f"/api/plans/{pid}/setpoints", json=_SP, headers=_ex())
    rec = client.get(f"/api/plans/{pid}", headers=_ex()).json()["recommendation"]
    assert rec["predicted_kpis"] is None and rec.get("needs_revalidation") is True
    # approval is blocked until re-validation
    assert client.post(f"/api/plans/{pid}/approve", headers=_ex()).status_code == 409


def test_create_plan_rejects_bad_grid(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11", "grid": 1}, headers=_op())
    assert r.status_code == 422
    assert "grid" in r.json()["detail"]


def test_create_plan_accepts_valid(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11", "grid": 5}, headers=_op())
    assert r.status_code == 202


def test_get_trajectory_endpoint(client):
    from webapp.store import PlanStore  # noqa: F401
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    r = client.get(f"/api/plans/{pid}/trajectory", headers=_op())
    assert r.status_code == 200
    body = r.json()
    assert "nominal" in body and "worst" in body  # empty until a real run emits CSVs


def test_is_terminal_table():
    from webapp.main import is_terminal
    assert is_terminal("pending_approval") and is_terminal("approved") and is_terminal("deployed")
    assert is_terminal("failed") and is_terminal("blocked_unsafe") and is_terminal("infeasible_fallback")
    assert not is_terminal("queued") and not is_terminal("running") and not is_terminal("deploying")


def test_progress_frame_shape(tmp_path):
    from webapp.main import progress_frame
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2013-11-11", {})
    store.write_progress("p1", {"level": 1, "evals": 5, "best_score": 0.9})
    frame = progress_frame(store, "p1")
    assert frame == {"progress": {"level": 1, "evals": 5, "best_score": 0.9}, "status": "queued"}
    assert progress_frame(store, "nope") == {"progress": {}, "status": None}


def test_stream_endpoint_emits_a_frame_for_a_terminal_plan(client):
    # the fixture's fake_runner saves a recommendation + sets status 'pending_approval' (terminal),
    # so the SSE generator emits one frame and closes — TestClient can read the full body.
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    r = client.get(f"/api/plans/{pid}/stream?token=op")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "data:" in r.text
    # the streamed frame carries the terminal status
    import json as _json
    payload = _json.loads(r.text.split("data:", 1)[1].split("\n\n", 1)[0].strip())
    assert payload["status"] == "pending_approval"


def test_stream_endpoint_rejects_bad_token(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    assert client.get(f"/api/plans/{pid}/stream?token=nope").status_code == 401
    assert client.get(f"/api/plans/{pid}/stream").status_code == 401          # missing token


def test_stream_endpoint_404_unknown_plan(client):
    assert client.get("/api/plans/does-not-exist/stream?token=op").status_code == 404
