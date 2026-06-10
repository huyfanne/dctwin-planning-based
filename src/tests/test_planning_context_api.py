"""Integration-ish test of GET /api/planning-context against the real forecaster/EPW assets
(pure Python — no EnergyPlus). Runs with cwd=src so models/ + data/ resolve."""
from fastapi.testclient import TestClient

from webapp.auth import TokenAuth
from webapp.main import create_app
from webapp.store import PlanStore


def _client(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    app = create_app(store=store, auth=TokenAuth({"op": "operator"}), run_sync=True)
    return TestClient(app)


def test_planning_context_shape_and_data(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/planning-context?week_start=2024-11-08&days=7",
              headers={"Authorization": "Bearer op"})
    assert r.status_code == 200
    d = r.json()
    assert d["week_start"] == "2024-11-08" and d["days"] == 7
    assert d["it_load"]["unit"] == "kW" and d["weather"]["unit"] == "°C"
    # in-coverage week -> forecast IT load + both weather windows are populated
    assert len(d["it_load"]["forecast"]) == 7 * 24 * 4
    assert len(d["weather"]["forecast"]) > 0
    assert len(d["weather"]["past"]) > 0                       # Nov 1-7 weather exists
    fc0 = d["it_load"]["forecast"][0]
    assert "t" in fc0 and "kw" in fc0 and fc0["kw"] > 0
    # no prior plan in a fresh store -> as-operated fallback with three setpoints
    ps = d["previous_setpoints"]
    assert ps is not None and ps["source"] == "as_operated"
    assert set(ps["setpoints"]) == {
        "crah_supply_air_temperature_c",
        "crah_supply_air_mass_flow_rate_kg_s",
        "chilled_water_supply_temperature_c"}


def test_planning_context_requires_auth(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/planning-context?week_start=2024-11-08").status_code == 401


def test_planning_context_bad_date_is_empty_not_500(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/planning-context?week_start=not-a-date",
              headers={"Authorization": "Bearer op"})
    assert r.status_code == 200
    d = r.json()
    assert d["it_load"]["past"] == [] and d["weather"]["forecast"] == []
    assert d["previous_setpoints"] is None
