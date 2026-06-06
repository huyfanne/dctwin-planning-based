from planner.recalibrator import recalibrate
from planner.calibrator import Calibration


def test_recalibrate_is_a_documented_noop_seam():
    cal = Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                      n_weeks=3, version="weeks-3")
    assert recalibrate(cal, history=[{"week_start": "2013-11-11"}]) is None
    assert recalibrate(cal, history=[], min_weeks=8) is None
