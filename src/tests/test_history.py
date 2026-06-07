import pandas as pd
from datetime import date
from planner.history import advance_history


def test_advance_history_fresh_file_schema(tmp_path):
    """Writing to a fresh file produces exactly realized keys + week_start as columns."""
    csv = tmp_path / "realized_history.csv"
    realized = {"total_hvac_energy_kwh": 30000.0, "pue_mean": 1.2,
                "inlet_temp_max_c": 26.1, "inlet_violation_steps": 0}
    advance_history(realized, date(2013, 11, 11), str(csv))
    df = pd.read_csv(csv)
    assert len(df) == 1
    expected_cols = {"week_start"} | set(realized.keys())
    assert set(df.columns) == expected_cols
    assert df.iloc[0]["week_start"] == "2013-11-11"
    assert df.iloc[0]["total_hvac_energy_kwh"] == 30000.0


def test_advance_history_appends_realized_week(tmp_path):
    csv = tmp_path / "his.csv"
    pd.DataFrame({"week_start": ["2013-11-04"], "total_hvac_energy_kwh": [31000.0],
                  "inlet_temp_max_c": [25.9]}).to_csv(csv, index=False)
    realized = {"total_hvac_energy_kwh": 30000.0, "inlet_temp_max_c": 26.1,
                "pue_mean": 1.2, "inlet_violation_steps": 0}
    advance_history(realized, date(2013, 11, 11), str(csv))
    df = pd.read_csv(csv)
    assert len(df) == 2
    assert df.iloc[-1]["week_start"] == "2013-11-11"
    assert df.iloc[-1]["total_hvac_energy_kwh"] == 30000.0


def test_advance_history_is_idempotent_per_week(tmp_path):
    csv = tmp_path / "his.csv"
    pd.DataFrame({"week_start": ["2013-11-11"], "total_hvac_energy_kwh": [1.0]}).to_csv(csv, index=False)
    advance_history({"total_hvac_energy_kwh": 30000.0}, date(2013, 11, 11), str(csv))
    df = pd.read_csv(csv)
    assert len(df) == 1                      # replaced, not duplicated
    assert df.iloc[-1]["total_hvac_energy_kwh"] == 30000.0


import json as _json
from planner.history import advance_calibration


def test_advance_calibration_pairs_predicted_and_realized(tmp_path):
    path = str(tmp_path / "calibration_history.json")
    predicted = {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    realized = {"total_hvac_energy_kwh": 105.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.5}
    advance_calibration(predicted, realized, date(2013, 11, 11), path)
    hist = _json.loads(open(path).read())
    assert len(hist) == 1
    assert hist[0]["week_start"] == "2013-11-11"
    assert hist[0]["predicted"]["total_hvac_energy_kwh"] == 100.0
    assert hist[0]["realized"]["total_hvac_energy_kwh"] == 105.0


def test_advance_calibration_idempotent_per_week(tmp_path):
    path = str(tmp_path / "calibration_history.json")
    advance_calibration({"a": 1}, {"a": 2}, date(2013, 11, 11), path)
    advance_calibration({"a": 10}, {"a": 20}, date(2013, 11, 11), path)
    hist = _json.loads(open(path).read())
    assert len(hist) == 1 and hist[0]["realized"]["a"] == 20


def test_refit_from_history_is_documented_noop(tmp_path, monkeypatch):
    import runpy
    from planner.history import refit_from_history
    called = {"ran": False}
    monkeypatch.setattr(runpy, "run_path", lambda *a, **k: called.__setitem__("ran", True))
    assert refit_from_history() is None          # returns None
    assert called["ran"] is False                # does NOT re-run fit_forecaster
