import math
from planner.robust import make_scenarios, scenario_spread
from planner.plant import DEFAULT_PLANT
from planner.calibrator import Calibration


def test_make_scenarios_deterministic_spread():
    scs = make_scenarios(DEFAULT_PLANT, n=3, spread=0.1)
    assert len(scs) == 3
    base_fan = DEFAULT_PLANT.perturbations[0].factor
    assert math.isclose(scs[0].perturbations[0].factor, base_fan * 0.9)
    assert math.isclose(scs[1].perturbations[0].factor, base_fan * 1.0)
    assert math.isclose(scs[2].perturbations[0].factor, base_fan * 1.1)


def test_make_scenarios_n1_is_base():
    scs = make_scenarios(DEFAULT_PLANT, n=1, spread=0.1)
    assert len(scs) == 1 and scs[0] == DEFAULT_PLANT


def test_scenario_spread_cold_start_and_widens():
    assert scenario_spread(None) == 0.1
    assert scenario_spread(Calibration({}, {}, 0, "weeks-0")) == 0.1
    wide = scenario_spread(Calibration({}, {"inlet_temp_max_c": 1.0}, 3, "weeks-3"),
                           base_spread=0.1, sigma_ref=1.0)
    assert wide == 0.2
