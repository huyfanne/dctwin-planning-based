import pandas as pd
from datetime import date
from planner.history import advance_history


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
