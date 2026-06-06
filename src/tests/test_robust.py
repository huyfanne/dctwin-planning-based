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


from planner.robust import RobustResult, robust_select
from planner.objective import ObjectiveWeights
from planner.types import Setpoints, WeeklyKPI


def _kpi(energy, inlet, viol=0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True,
                     inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)


def test_robust_select_prefers_robust_feasible_then_cvar():
    sp_a, sp_b = Setpoints(24, 8, 17), Setpoints(22, 10, 15)
    finalists = [(sp_a, _kpi(100, 24), 100.0), (sp_b, _kpi(110, 23), 110.0)]
    scenario_kpis = [
        [_kpi(100, 24), _kpi(105, 27, viol=3)],   # finalist A: scenario 2 breaches cap
        [_kpi(110, 23), _kpi(112, 25)],           # finalist B: feasible everywhere
    ]
    rr = robust_select(finalists, scenario_kpis, ObjectiveWeights())
    assert rr.winner == sp_b
    assert rr.robust_feasible is True
    assert rr.n_scenarios == 2
    assert rr.confidence_bands["inlet_temp_max_c"]["max"] == 25.0
    assert rr.cvar_energy_kwh == 112.0


def test_robust_select_all_infeasible_returns_least_bad():
    sp = Setpoints(24, 8, 17)
    finalists = [(sp, _kpi(100, 24), 100.0)]
    scenario_kpis = [[_kpi(100, 28, viol=5)]]
    rr = robust_select(finalists, scenario_kpis, ObjectiveWeights())
    assert rr.winner == sp and rr.robust_feasible is False
