from planner.recalibrator import fit_plant_factors, recalibrate
from planner.calibrator import Calibration


def test_recalibrate_returns_none_below_min_weeks():
    cal = Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                      n_weeks=3, version="weeks-3")
    assert recalibrate(cal, history=[{"week_start": "2013-11-11"}]) is None
    assert recalibrate(cal, history=[], min_weeks=8) is None


def _week(pred, real, ws="2026-01-05"):
    return {"week_start": ws,
            "predicted": {"total_hvac_energy_kwh": pred},
            "realized": {"total_hvac_energy_kwh": real}}


def test_fit_plant_factors_maps_energy_bias_to_fan_efficiency():
    # 4 weeks of +10% realized energy -> b = 0.10 -> factor 1/1.1 (real fans are
    # less efficient than modeled)
    out = fit_plant_factors([_week(1000.0, 1100.0)] * 4)
    assert out is not None
    assert abs(out["fan_total_efficiency_factor"] - 1 / 1.1) < 1e-9
    assert abs(out["bias_fraction"] - 0.10) < 1e-9
    assert out["n_weeks"] == 4


def test_fit_plant_factors_winsorizes_wild_weeks_and_clips_factor():
    # One wild 5x week is winsorized to ratio 2.0: mean = (3*1.1 + 2.0)/4 = 1.325
    # -> 1/1.325 = 0.7547 -> clipped to the conservative 0.85 floor.
    out = fit_plant_factors([_week(1000.0, 1100.0)] * 3 + [_week(1000.0, 5000.0)])
    assert out["fan_total_efficiency_factor"] == 0.85


def test_fit_plant_factors_clips_factor_upper():
    # Ratio 0.6 per week -> b = -0.4 -> 1/0.6 = 1.667 -> clipped to 1.15.
    out = fit_plant_factors([_week(1000.0, 600.0)] * 4)
    assert out["fan_total_efficiency_factor"] == 1.15


def test_fit_plant_factors_none_below_min_weeks_or_small_bias():
    assert fit_plant_factors([_week(1000.0, 1100.0)] * 3) is None       # 3 < min_weeks=4
    assert fit_plant_factors([_week(1000.0, 1005.0)] * 4) is None       # |b| = 0.5% < 1%
    assert fit_plant_factors([]) is None


def test_fit_plant_factors_skips_invalid_pairs():
    hist = [_week(1000.0, 1100.0)] * 3 + [
        {"week_start": "x", "predicted": {}, "realized": {"total_hvac_energy_kwh": 1.0}},
        {"week_start": "y", "predicted": {"total_hvac_energy_kwh": 0.0},
         "realized": {"total_hvac_energy_kwh": 1.0}},
    ]
    assert fit_plant_factors(hist) is None      # only 3 valid weeks -> below min


def test_recalibrate_returns_perturbation_proposal():
    cal = Calibration(bias={}, sigma={}, n_weeks=4, version="weeks-4")
    prop = recalibrate(cal, [_week(1000.0, 1100.0)] * 4)
    assert prop is not None
    [p] = prop["perturbations"]
    assert p["table"] == "Fan_VariableVolume"
    assert p["field"] == "fan_total_efficiency"
    assert abs(p["factor"] - 1 / 1.1) < 1e-9
    assert prop["basis"]["n_weeks"] == 4
    assert abs(prop["basis"]["bias_fraction"] - 0.10) < 1e-9
    assert prop["basis"]["calibration_version"] == "weeks-4"


def test_recalibrate_none_on_small_bias():
    cal = Calibration(bias={}, sigma={}, n_weeks=4, version="weeks-4")
    assert recalibrate(cal, [_week(1000.0, 1005.0)] * 4) is None
