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
    assert math.isclose(cal.sigma["total_hvac_energy_kwh"], 2500.0)
    assert cal.sigma["inlet_temp_max_c"] == 0.5


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


from planner.calibrator import SIGMA_PRIOR, RESIDUAL_CLIP


def test_sigma_floor_at_cold_start():
    # a single deploy must NOT yield sigma=0 (which would brick the next plan)
    hist = [{"week_start": "2013-11-11",
             "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
             "realized":  {"total_hvac_energy_kwh": 130.0, "pue_mean": 1.2, "inlet_temp_max_c": 28.0}}]
    cal = fit_calibration(hist)
    assert cal.sigma["inlet_temp_max_c"] == SIGMA_PRIOR["inlet_temp_max_c"]
    assert cal.sigma["inlet_temp_max_c"] > 0.0


def test_residual_clip_bounds_one_wild_week():
    # an absurd single residual is winsorized to the clip bound before it becomes the bias
    hist = [{"week_start": "2013-11-11",
             "predicted": {"inlet_temp_max_c": 24.0},
             "realized":  {"inlet_temp_max_c": 24.0 + 10 * RESIDUAL_CLIP["inlet_temp_max_c"]}}]
    cal = fit_calibration(hist)
    assert cal.bias["inlet_temp_max_c"] == RESIDUAL_CLIP["inlet_temp_max_c"]


def test_sigma_shrinks_toward_sample_as_n_grows():
    # the conservative prior fades as 1/n toward the empirical sample std (~1.0 here)
    # as weeks accumulate (residuals alternate +-1 around mean 0 -> sample std 1.0)
    def sigma_for_n(n):
        hist = [{"predicted": {"total_hvac_energy_kwh": 101.0},
                 "realized":  {"total_hvac_energy_kwh": 101.0 + (1.0 if i % 2 else -1.0)}}
                for i in range(n)]
        return fit_calibration(hist).sigma["total_hvac_energy_kwh"]
    s2, s10, s1000 = sigma_for_n(2), sigma_for_n(10), sigma_for_n(1000)
    assert s2 > s10 > s1000          # monotonic shrinkage as n grows
    assert s1000 < 10.0              # well below the 5000 prior, heading toward sample (~1.0)


def test_sigma_post_blends_prior_with_measured_residuals():
    """sigma_post = sqrt((n*s^2 + prior^2)/(n+1)) — prior counts as one pseudo-week."""
    # n=1: a single (near-perfect) week -> sample std 0 -> post = prior/sqrt(2),
    # NOT the full prior (the fading floor stays at the full prior here by design).
    one = [{"predicted": {"inlet_temp_max_c": 24.0}, "realized": {"inlet_temp_max_c": 24.005}}]
    cal1 = fit_calibration(one)
    assert math.isclose(cal1.sigma_post["inlet_temp_max_c"],
                        SIGMA_PRIOR["inlet_temp_max_c"] / math.sqrt(2.0), rel_tol=1e-9)
    assert cal1.sigma["inlet_temp_max_c"] == SIGMA_PRIOR["inlet_temp_max_c"]  # floor unchanged
    # n=4 accurate weeks (residuals +-0.01 -> s=0.01): post ~ sqrt((4e-4+1)/5) ~ 0.447
    four = [{"predicted": {"inlet_temp_max_c": 24.0},
             "realized": {"inlet_temp_max_c": 24.0 + (0.01 if i % 2 else -0.01)}}
            for i in range(4)]
    cal4 = fit_calibration(four)
    assert math.isclose(cal4.sigma_post["inlet_temp_max_c"],
                        ((4 * 0.01 ** 2 + 1.0) / 5.0) ** 0.5, rel_tol=1e-9)
    # monotone: more accurate evidence -> tighter posterior
    assert cal4.sigma_post["inlet_temp_max_c"] < cal1.sigma_post["inlet_temp_max_c"]


def test_sigma_post_roundtrips_and_falls_back():
    cal = fit_calibration([{"predicted": {"inlet_temp_max_c": 24.0},
                            "realized": {"inlet_temp_max_c": 24.0}}])
    d = cal.to_dict()
    assert "sigma_post" in d
    back = Calibration.from_dict(d)
    assert back.sigma_post_for("inlet_temp_max_c") == cal.sigma_post["inlet_temp_max_c"]
    # a legacy dict (no sigma_post) falls back to the floor-pinned sigma — never less
    # conservative than the old behavior
    legacy = Calibration.from_dict({"bias": {}, "sigma": {"inlet_temp_max_c": 0.8},
                                    "n_weeks": 2, "version": "weeks-2"})
    assert legacy.sigma_post_for("inlet_temp_max_c") == 0.8
