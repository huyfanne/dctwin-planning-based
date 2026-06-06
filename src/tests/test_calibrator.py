import math
from planner.calibrator import Calibration, fit_calibration, CALIB_KEYS
from planner.types import WeeklyKPI


def _kpi(energy=100.0, pue=1.2, inlet=24.0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=pue, inlet_temp_max=inlet,
                     inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                     inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0,
                     zone_temp_band_steps=0.0)


def test_fit_calibration_bias_and_sigma():
    hist = [
        {"week_start": "2013-11-04",
         "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
         "realized":  {"total_hvac_energy_kwh": 102.0, "pue_mean": 1.2, "inlet_temp_max_c": 25.0}},
        {"week_start": "2013-11-11",
         "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
         "realized":  {"total_hvac_energy_kwh": 104.0, "pue_mean": 1.2, "inlet_temp_max_c": 25.0}},
    ]
    cal = fit_calibration(hist)
    assert cal.n_weeks == 2
    assert cal.bias["total_hvac_energy_kwh"] == 3.0
    assert cal.bias["inlet_temp_max_c"] == 1.0
    assert math.isclose(cal.sigma["total_hvac_energy_kwh"], 1.0)
    assert cal.sigma["inlet_temp_max_c"] == 0.0


def test_fit_calibration_identity_when_empty():
    cal = fit_calibration([])
    assert cal.n_weeks == 0
    assert cal.bias == {} and cal.sigma == {}


def test_apply_corrects_weeklykpi():
    cal = Calibration(bias={"total_hvac_energy_kwh": 3.0, "inlet_temp_max_c": 1.0, "pue_mean": 0.05},
                      sigma={"inlet_temp_max_c": 0.5}, n_weeks=2, version="weeks-2")
    corrected = cal.apply(_kpi(energy=100.0, pue=1.2, inlet=24.0))
    assert corrected.total_hvac_energy_kwh == 103.0
    assert corrected.inlet_temp_max == 25.0
    assert corrected.pue_mean == 1.25
    assert cal.sigma_for("inlet_temp_max_c") == 0.5
    assert CALIB_KEYS == ("total_hvac_energy_kwh", "pue_mean", "inlet_temp_max_c")


import json as _json
from pathlib import Path
from planner.calibrator import load_calibration, save_calibration, recompute_calibration


def test_save_load_roundtrip(tmp_path):
    cal = Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                      n_weeks=2, version="weeks-2")
    p = str(tmp_path / "calibration.json")
    save_calibration(cal, p)
    got = load_calibration(p)
    assert got.bias["inlet_temp_max_c"] == 1.0 and got.n_weeks == 2


def test_load_missing_returns_identity(tmp_path):
    got = load_calibration(str(tmp_path / "nope.json"))
    assert got.n_weeks == 0 and got.bias == {}


def test_recompute_calibration_from_history(tmp_path):
    hist = [{"week_start": "2013-11-11",
             "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
             "realized":  {"total_hvac_energy_kwh": 105.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}}]
    hpath = tmp_path / "calibration_history.json"
    hpath.write_text(_json.dumps(hist))
    out = tmp_path / "calibration.json"
    cal = recompute_calibration(str(hpath), str(out))
    assert cal.bias["total_hvac_energy_kwh"] == 5.0
    assert load_calibration(str(out)).bias["total_hvac_energy_kwh"] == 5.0
