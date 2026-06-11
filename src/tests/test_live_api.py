import time

import pytest
from fastapi.testclient import TestClient

from webapp.auth import TokenAuth
from webapp.main import create_app
from webapp.store import PlanStore
from webapp.telemetry import TelemetryStore


@pytest.fixture
def env(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    tstore = TelemetryStore(db_path=str(tmp_path / "runs" / "telemetry.db"))
    auth = TokenAuth({"op": "operator", "ex": "expert"})
    app = create_app(store=store, auth=auth, run_sync=True, telemetry_store=tstore)
    return TestClient(app), store, tstore


def _op():
    return {"Authorization": "Bearer op"}


_SP = {"crah_supply_air_temperature_c": 24.0,
       "crah_supply_air_mass_flow_rate_kg_s": 6.2,
       "chilled_water_supply_temperature_c": 18.0}


def _deploy_plan(store, plan_id="p1", setpoints=_SP):
    store.create_plan(plan_id, "2024-11-11", {})
    store.save_recommendation(plan_id, {"plan_id": plan_id, "status": "deployed",
                                        "setpoints": setpoints})
    store.set_status(plan_id, "deployed")


# ---------------------------------------------------------------- auth (fail-closed)

def test_live_routes_require_operator_token(env):
    client, _, _ = env
    assert client.get("/api/live").status_code == 401
    assert client.get("/api/live/series").status_code == 401
    assert client.post("/api/telemetry", json={"points": {"pue": 1.3}}).status_code == 401
    assert client.get("/api/live/stream").status_code == 401            # missing token
    assert client.get("/api/live/stream?token=nope").status_code == 401  # bad token


# ---------------------------------------------------------------- ingest + snapshot

def test_post_telemetry_then_live_snapshot(env):
    client, _, _ = env
    r = client.post("/api/telemetry",
                    json={"ts": 1_000.0, "points": {"rack_inlet_c/ite-1": 24.9,
                                                    "hall_power_kw": 480.0}},
                    headers=_op())
    assert r.status_code == 202
    assert r.json() == {"written": 2, "ts": 1_000.0}

    body = client.get("/api/live", headers=_op()).json()
    assert body["ts"] == 1_000.0
    assert body["points"]["hall_power_kw"] == {"ts": 1_000.0, "value": 480.0}
    assert body["alerts"] == []                              # 24.9 is below the warn line
    assert body["simulated"] is False                        # real push, not the sim feed
    assert body["compliance"]["ok"] is None                  # nothing deployed yet


def test_post_telemetry_defaults_ts_to_now(env):
    client, _, tstore = env
    before = time.time()
    r = client.post("/api/telemetry", json={"points": {"pue": 1.31}}, headers=_op())
    assert r.status_code == 202
    assert before <= r.json()["ts"] <= time.time()
    assert tstore.latest()["pue"]["value"] == 1.31


def test_post_telemetry_rejects_non_numeric(env):
    client, _, _ = env
    r = client.post("/api/telemetry", json={"points": {"pue": "hot"}}, headers=_op())
    assert r.status_code == 422


# ---------------------------------------------------------------- alerts

def test_live_alerts_warn_then_critical(env):
    client, _, _ = env
    client.post("/api/telemetry", json={"points": {"rack_inlet_c/ite-3": 25.3}},
                headers=_op())
    alerts = client.get("/api/live", headers=_op()).json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["level"] == "warn" and alerts[0]["point"] == "rack_inlet_c/ite-3"

    client.post("/api/telemetry", json={"points": {"rack_inlet_c/ite-3": 26.1}},
                headers=_op())
    alerts = client.get("/api/live", headers=_op()).json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["level"] == "critical" and alerts[0]["value"] == 26.1


# ---------------------------------------------------------------- compliance

def test_live_compliance_ok_against_deployed_plan(env):
    client, store, _ = env
    _deploy_plan(store)
    client.post("/api/telemetry",
                json={"points": {"held/sat_c": 24.3, "held/flow_kg_s": 6.0,
                                 "held/chwst_c": 18.2}}, headers=_op())
    c = client.get("/api/live", headers=_op()).json()["compliance"]
    assert c["ok"] is True
    assert c["commanded"] == {"sat": 24.0, "flow": 6.2, "chwst": 18.0}
    assert c["deltas"]["sat"] == pytest.approx(0.3)


def test_live_compliance_breach(env):
    client, store, _ = env
    _deploy_plan(store)
    client.post("/api/telemetry",
                json={"points": {"held/sat_c": 25.2, "held/flow_kg_s": 6.2,
                                 "held/chwst_c": 18.0}}, headers=_op())
    c = client.get("/api/live", headers=_op()).json()["compliance"]
    assert c["ok"] is False
    assert c["deltas"]["sat"] == pytest.approx(1.2)


def test_live_compliance_null_without_deployed_plan(env):
    client, store, _ = env
    store.create_plan("p1", "2024-11-11", {})               # exists but never deployed
    store.save_recommendation("p1", {"plan_id": "p1", "status": "pending_approval",
                                     "setpoints": _SP})
    client.post("/api/telemetry", json={"points": {"held/sat_c": 24.0}}, headers=_op())
    c = client.get("/api/live", headers=_op()).json()["compliance"]
    assert c["ok"] is None and c["commanded"] is None


# ---------------------------------------------------------------- series

def test_live_series_shape_and_worst_inlet(env):
    client, _, _ = env
    now = time.time()
    for i in range(3):
        client.post("/api/telemetry",
                    json={"ts": now - 120.0 + i * 60.0,
                          "points": {"hall_power_kw": 480.0 + i, "pue": 1.30 + 0.01 * i,
                                     "rack_inlet_c/ite-1": 23.0 + i,
                                     "rack_inlet_c/ite-2": 24.0}}, headers=_op())
    body = client.get("/api/live/series?minutes=30", headers=_op()).json()
    assert body["minutes"] == 30
    assert [r["value"] for r in body["hall_power_kw"]] == [480.0, 481.0, 482.0]
    assert [r["value"] for r in body["pue"]] == pytest.approx([1.30, 1.31, 1.32])
    assert [r["value"] for r in body["worst_inlet_c"]] == [24.0, 24.0, 25.0]
    assert all(set(r) == {"ts", "value"} for r in body["hall_power_kw"])


def test_live_series_respects_minutes_window(env):
    client, _, _ = env
    now = time.time()
    client.post("/api/telemetry", json={"ts": now - 3600.0,
                                        "points": {"hall_power_kw": 1.0}}, headers=_op())
    client.post("/api/telemetry", json={"ts": now - 10.0,
                                        "points": {"hall_power_kw": 2.0}}, headers=_op())
    body = client.get("/api/live/series?minutes=5", headers=_op()).json()
    assert [r["value"] for r in body["hall_power_kw"]] == [2.0]


# ---------------------------------------------------------------- SSE endpoint

def test_live_stream_endpoint_emits_first_frame(env, monkeypatch):
    client, _, _ = env
    # Bound the stream: live has no terminal state, so TestClient teardown would
    # deadlock waiting on a generator that never observes the disconnect. The
    # backstops resolve at call time inside live_sse_stream -> shrink them here
    # and the generator self-terminates right after the asserted first frame.
    import webapp.telemetry as _t
    monkeypatch.setattr(_t, "_LIVE_MAX_ITERS", 3)
    monkeypatch.setattr(_t, "_LIVE_POLL_S", 0.01)
    client.post("/api/telemetry", json={"ts": 42.0, "points": {"pue": 1.29}},
                headers=_op())
    with client.stream("GET", "/api/live/stream?token=op") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                import json as _json
                frame = _json.loads(line[len("data:"):].strip())
                assert frame["points"]["pue"]["value"] == 1.29
                break


# ---------------------------------------------------------------- sim feed wiring

def test_sim_feed_off_by_default(env, monkeypatch):
    monkeypatch.delenv("DTWIN_SIM_TELEMETRY", raising=False)
    client, _, tstore = env
    with client:                                             # run lifespan startup
        assert tstore.latest() == {}                         # no feed -> nothing written


def test_sim_feed_started_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DTWIN_SIM_TELEMETRY", "1")
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    tstore = TelemetryStore(db_path=str(tmp_path / "runs" / "telemetry.db"))
    app = create_app(store=store, auth=TokenAuth({"op": "operator"}), run_sync=True,
                     telemetry_store=tstore)
    with TestClient(app):
        deadline = time.time() + 2.0
        while not tstore.latest() and time.time() < deadline:
            time.sleep(0.02)
        latest = tstore.latest()
    assert latest.get("simulated", {}).get("value") == 1.0   # labelled sim data flowing
    assert len([k for k in latest if k.startswith("rack_inlet_c/")]) == 22
