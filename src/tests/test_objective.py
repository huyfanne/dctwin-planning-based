import math

from planner.objective import ObjectiveWeights, is_feasible, score, INFEASIBLE
from planner.types import WeeklyKPI


def _kpi(energy=100.0, inlet_viol=0, rh_viol=0, inlet_excess=0.0,
         rh_exc=0.0, zone=0.0, feasible=True):
    return WeeklyKPI(
        total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=inlet_viol, rh_violation_steps=rh_viol,
        feasible=feasible, inlet_excess_degc_steps=inlet_excess,
        rh_excursion_steps=rh_exc, zone_temp_band_steps=zone,
    )


def test_feasible_when_no_violations():
    assert is_feasible(_kpi(), ObjectiveWeights())


def test_infeasible_when_inlet_violation_exceeds_tol():
    w = ObjectiveWeights(inlet_tol_steps=0)
    assert not is_feasible(_kpi(inlet_viol=1), w)
    assert score(_kpi(inlet_viol=1), w) == INFEASIBLE


def test_inlet_tolerance_allows_small_violations():
    w = ObjectiveWeights(inlet_tol_steps=3)
    assert is_feasible(_kpi(inlet_viol=3), w)
    assert not is_feasible(_kpi(inlet_viol=4), w)


def test_rh_hard_constraint_toggle():
    soft = ObjectiveWeights(rh_hard=False)
    hard = ObjectiveWeights(rh_hard=True, rh_tol_steps=0)
    assert is_feasible(_kpi(rh_viol=5), soft)
    assert not is_feasible(_kpi(rh_viol=5), hard)


def test_score_dominated_by_energy_and_monotonic():
    w = ObjectiveWeights()
    assert score(_kpi(energy=100.0), w) < score(_kpi(energy=200.0), w)


def test_score_adds_soft_penalties():
    w = ObjectiveWeights(lambda_temp=2.0, lambda_rh=0.5, lambda_zone=0.25)
    base = score(_kpi(energy=100.0), w)
    pen = score(_kpi(energy=100.0, inlet_excess=3.0, rh_exc=4.0, zone=8.0), w)
    assert pen == base + 2.0 * 3.0 + 0.5 * 4.0 + 0.25 * 8.0


def test_unfeasible_flag_forces_infeasible():
    assert score(_kpi(feasible=False), ObjectiveWeights()) == INFEASIBLE


def test_rh_tolerance_boundary_when_hard():
    w = ObjectiveWeights(rh_hard=True, rh_tol_steps=3)
    assert is_feasible(_kpi(rh_viol=3), w)
    assert not is_feasible(_kpi(rh_viol=4), w)
