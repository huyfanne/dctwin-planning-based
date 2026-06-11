import random

import pytest

from webapp.telemetry import (
    N_RACKS,
    SimTelemetryFeed,
    TelemetryStore,
    commanded_setpoints,
    compute_alerts,
    compute_compliance,
    live_frame,
)


@pytest.fixture
def store(tmp_path):
    return TelemetryStore(db_path=str(tmp_path / "runs" / "telemetry.db"))


# ---------------------------------------------------------------- TelemetryStore

def test_write_and_latest_returns_newest_value_per_point(store):
    store.write({"hall_power_kw": 480.0, "pue": 1.30}, ts=100.0)
    store.write({"hall_power_kw": 495.0}, ts=200.0)
    latest = store.latest()
    assert latest["hall_power_kw"] == {"ts": 200.0, "value": 495.0}
    assert latest["pue"] == {"ts": 100.0, "value": 1.30}


def test_latest_empty_store(store):
    assert store.latest() == {}


def test_series_windows_and_orders_ascending(store):
    now = 10_000.0
    for i, v in enumerate([1.0, 2.0, 3.0, 4.0]):
        store.write({"pue": v}, ts=now - 90.0 + i * 30.0)   # ts: -90, -60, -30, 0
    s = store.series(["pue"], minutes=1.0, now=now)         # window = last 60 s
    assert [r["value"] for r in s["pue"]] == [2.0, 3.0, 4.0]
    assert [r["ts"] for r in s["pue"]] == sorted(r["ts"] for r in s["pue"])


def test_series_includes_requested_points_even_when_absent(store):
    store.write({"pue": 1.3}, ts=50.0)
    s = store.series(["pue", "hall_power_kw"], minutes=60.0, now=60.0)
    assert s["hall_power_kw"] == []
    assert len(s["pue"]) == 1


def test_series_stride_downsamples_and_keeps_newest(store):
    now = 100_000.0
    for i in range(1000):
        store.write({"hall_power_kw": float(i)}, ts=now - 1000.0 + i)
    s = store.series(["hall_power_kw"], minutes=30.0, max_rows=100, now=now)
    rows = s["hall_power_kw"]
    assert len(rows) <= 101                      # stride cap (+1 to keep the newest)
    assert rows[-1]["value"] == 999.0            # newest sample always survives
    assert rows[0]["value"] == 0.0               # oldest in-window sample survives


def test_worst_inlet_series_takes_max_per_snapshot(store):
    now = 1_000.0
    store.write({"rack_inlet_c/ite-1": 23.0, "rack_inlet_c/ite-2": 24.5,
                 "rack_inlet_c/ite-3": 22.8, "hall_power_kw": 480.0}, ts=now - 60.0)
    store.write({"rack_inlet_c/ite-1": 25.1, "rack_inlet_c/ite-2": 24.0}, ts=now)
    rows = store.worst_inlet_series(minutes=5.0, now=now)
    assert [r["value"] for r in rows] == [24.5, 25.1]       # hall_power never leaks in


# ---------------------------------------------------------------- SimTelemetryFeed

def test_sim_feed_snapshot_is_complete_and_labelled(store):
    feed = SimTelemetryFeed(store, now_fn=lambda: 1_000.0, rng=random.Random(0))
    snap = feed.snapshot()
    inlets = [k for k in snap if k.startswith("rack_inlet_c/")]
    assert len(inlets) == N_RACKS == 22
    assert snap["simulated"] == 1.0                          # honesty label, always on
    assert all(f"rack_inlet_c/ite-{i}" in snap for i in range(1, 23))
    for k in ("hall_power_kw", "pue", "rh_pct", "held/sat_c",
              "held/flow_kg_s", "held/chwst_c"):
        assert k in snap
    assert all(18.0 < snap[k] < 25.0 for k in inlets)        # nominal feed stays sub-warn
    assert 1.0 < snap["pue"] < 2.0


def test_sim_feed_is_deterministic_with_injected_rng_and_now(store):
    a = SimTelemetryFeed(store, now_fn=lambda: 5_000.0, rng=random.Random(7)).snapshot()
    b = SimTelemetryFeed(store, now_fn=lambda: 5_000.0, rng=random.Random(7)).snapshot()
    assert a == b


def test_sim_feed_held_tracks_commanded(store):
    cmd = {"sat": 22.5, "flow": 7.25, "chwst": 15.0}
    feed = SimTelemetryFeed(store, commanded_fn=lambda: cmd,
                            now_fn=lambda: 1_000.0, rng=random.Random(1))
    snap = feed.snapshot()
    assert abs(snap["held/sat_c"] - 22.5) < 0.3
    assert abs(snap["held/flow_kg_s"] - 7.25) < 0.3
    assert abs(snap["held/chwst_c"] - 15.0) < 0.3


def test_sim_feed_tick_writes_to_store(store):
    feed = SimTelemetryFeed(store, now_fn=lambda: 1_000.0, rng=random.Random(2))
    feed._tick()
    latest = store.latest()
    assert latest["simulated"] == {"ts": 1_000.0, "value": 1.0}
    assert len([k for k in latest if k.startswith("rack_inlet_c/")]) == 22


def test_sim_feed_thread_start_stop(store):
    feed = SimTelemetryFeed(store, interval_s=0.01, now_fn=None, rng=random.Random(3))
    feed.start()
    try:
        import time
        deadline = time.time() + 2.0
        while not store.latest() and time.time() < deadline:
            time.sleep(0.01)
    finally:
        feed.stop()
    assert "simulated" in store.latest()
    assert feed._thread is None                              # stop() joins + clears


# ---------------------------------------------------------------- alerts / compliance

def test_alerts_nominal_warn_critical_thresholds():
    assert compute_alerts({"rack_inlet_c/ite-1": 24.9}) == []
    warn = compute_alerts({"rack_inlet_c/ite-1": 25.3})
    assert len(warn) == 1 and warn[0]["level"] == "warn"
    assert warn[0]["point"] == "rack_inlet_c/ite-1" and warn[0]["value"] == 25.3
    crit = compute_alerts({"rack_inlet_c/ite-1": 26.1})
    assert len(crit) == 1 and crit[0]["level"] == "critical"


def test_alerts_ignore_non_inlet_points_and_sort_by_point():
    alerts = compute_alerts({"hall_power_kw": 999.0, "pue": 26.5,
                             "rack_inlet_c/ite-2": 26.2, "rack_inlet_c/ite-1": 25.1})
    assert [a["point"] for a in alerts] == ["rack_inlet_c/ite-1", "rack_inlet_c/ite-2"]
    assert [a["level"] for a in alerts] == ["warn", "critical"]


def test_compliance_ok_within_tolerance():
    cmd = {"sat": 24.0, "flow": 6.2, "chwst": 18.0}
    vals = {"held/sat_c": 24.4, "held/flow_kg_s": 6.0, "held/chwst_c": 17.6}
    c = compute_compliance(cmd, vals)
    assert c["ok"] is True
    assert c["commanded"] == cmd
    assert c["held"] == {"sat": 24.4, "flow": 6.0, "chwst": 17.6}
    assert c["deltas"]["sat"] == pytest.approx(0.4)


def test_compliance_breach_beyond_half_degree():
    cmd = {"sat": 24.0, "flow": 6.2, "chwst": 18.0}
    vals = {"held/sat_c": 24.6, "held/flow_kg_s": 6.2, "held/chwst_c": 18.0}
    c = compute_compliance(cmd, vals)
    assert c["ok"] is False
    assert c["deltas"]["sat"] == pytest.approx(0.6)


def test_compliance_null_when_no_deployed_plan_or_no_held():
    vals = {"held/sat_c": 24.0, "held/flow_kg_s": 6.2, "held/chwst_c": 18.0}
    c = compute_compliance(None, vals)
    assert c["ok"] is None and c["commanded"] is None and c["held"] is not None
    c2 = compute_compliance({"sat": 24.0, "flow": 6.2, "chwst": 18.0}, {"pue": 1.3})
    assert c2["ok"] is None and c2["held"] is None


# ---------------------------------------------------------------- frame + commanded

class _FakePlanStore:
    def __init__(self, plans, recs):
        self._plans, self._recs = plans, recs

    def list_plans(self):
        return self._plans

    def get_recommendation(self, plan_id):
        return self._recs.get(plan_id)


_SP = {"crah_supply_air_temperature_c": 24.0,
       "crah_supply_air_mass_flow_rate_kg_s": 6.2,
       "chilled_water_supply_temperature_c": 18.0}


def test_commanded_setpoints_latest_deployed_plan():
    ps = _FakePlanStore(
        [{"plan_id": "p2", "status": "deployed"},          # newest first
         {"plan_id": "p1", "status": "deployed"}],
        {"p2": {"setpoints": _SP}, "p1": {"setpoints": {**_SP, "crah_supply_air_temperature_c": 20.0}}})
    assert commanded_setpoints(ps) == {"sat": 24.0, "flow": 6.2, "chwst": 18.0}


def test_commanded_setpoints_none_when_nothing_deployed():
    ps = _FakePlanStore([{"plan_id": "p1", "status": "pending_approval"}],
                        {"p1": {"setpoints": _SP}})
    assert commanded_setpoints(ps) is None
    assert commanded_setpoints(_FakePlanStore([], {})) is None


def test_live_frame_shape(store):
    store.write({"rack_inlet_c/ite-1": 25.4, "hall_power_kw": 480.0,
                 "held/sat_c": 24.1, "held/flow_kg_s": 6.2, "held/chwst_c": 18.0,
                 "simulated": 1.0}, ts=777.0)
    frame = live_frame(store, {"sat": 24.0, "flow": 6.2, "chwst": 18.0})
    assert frame["ts"] == 777.0
    assert frame["points"]["hall_power_kw"]["value"] == 480.0
    assert frame["simulated"] is True
    assert frame["alerts"][0]["level"] == "warn"
    assert frame["compliance"]["ok"] is True


def test_live_frame_empty_store(store):
    frame = live_frame(store, None)
    assert frame == {"ts": None, "points": {}, "alerts": [],
                     "compliance": {"commanded": None, "held": None,
                                    "ok": None, "deltas": {}},
                     "simulated": False}


# ---------------------------------------------------------------- live SSE generator

def test_live_sse_stream_emits_frames_keepalive_and_respects_disconnect(store):
    import asyncio
    import json as _json
    from webapp.telemetry import live_sse_stream

    store.write({"hall_power_kw": 480.0}, ts=1.0)
    state = {"polls": 0}

    def frame_fn():
        return live_frame(store, None)

    async def collect():
        out = []

        async def disc():
            return state["polls"] >= 8           # client goes away after a few polls

        async def sleep(_):
            state["polls"] += 1
            if state["polls"] == 5:
                store.write({"hall_power_kw": 481.0}, ts=2.0)   # change -> new frame

        async for chunk in live_sse_stream(frame_fn, disc, sleep=sleep,
                                           keepalive_every=2):
            out.append(chunk)
        return out

    chunks = asyncio.run(collect())
    datas = [c for c in chunks if c.startswith("data:")]
    assert len(datas) == 2                                   # initial frame + the change
    assert any(c.startswith(": keepalive") for c in chunks)  # idle stretch covered
    last = _json.loads(datas[-1][len("data: "):].strip())
    assert last["points"]["hall_power_kw"]["value"] == 481.0
    assert state["polls"] < 20                               # disconnect actually stopped it
