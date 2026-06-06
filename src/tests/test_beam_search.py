import pytest

from planner.beam_search import BeamConfig, BeamPlanner, PlanResult
from planner.objective import ObjectiveWeights, is_feasible
from planner.mock_evaluator import MockSurface, MockEvaluator
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


def res_evals_cap(planner):
    c = planner.config
    return c.grid ** 3 + c.levels * c.beam_width * c.neighbors


def test_converges_near_energy_optimum_when_unconstrained():
    ev = MockEvaluator(MockSurface(sat_opt=24.0, flow_opt=8.0, chwst_opt=17.0,
                                   energy_base=100.0, inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=5, beam_width=5, levels=3, neighbors=6))
    res = planner.plan()
    assert res.feasible
    assert res.best_kpi.total_hvac_energy_kwh < 100.5
    assert res.evals <= res_evals_cap(planner)
    # best score per level is non-increasing
    assert all(b <= a for a, b in zip(res.history[:-1], res.history[1:]))


def test_never_returns_infeasible_candidate():
    ev = MockEvaluator(MockSurface(inlet_cap=22.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=5, beam_width=5, levels=3, neighbors=6))
    res = planner.plan()
    assert res.feasible
    assert res.best_kpi.inlet_temp_max <= 22.0 + 1e-9
    assert is_feasible(res.best_kpi, ObjectiveWeights())


def test_reports_infeasible_when_no_feasible_region():
    ev = MockEvaluator(MockSurface(inlet_cap=0.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=1, neighbors=6))
    res = planner.plan()
    assert res.feasible is False
    assert res.best is not None


def test_respects_eval_budget():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=5,
                                     neighbors=6, max_evals=30))
    res = planner.plan()
    assert res.evals <= 30


def test_deterministic():
    surf = MockSurface(inlet_cap=999.0)
    cfg = BeamConfig(grid=4, beam_width=4, levels=2, neighbors=6)
    r1 = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(surf), ObjectiveWeights(), cfg).plan()
    r2 = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(surf), ObjectiveWeights(), cfg).plan()
    assert r1.best.as_tuple() == r2.best.as_tuple()
    assert r1.best_score == r2.best_score


def test_evaluates_in_batches_one_call_per_level():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=2, neighbors=6))
    planner.plan()
    assert 1 <= ev.call_count <= 3


def test_grid_must_be_at_least_two():
    ev = MockEvaluator()
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=1))
    with pytest.raises(ValueError):
        planner.plan()


def test_returned_candidate_within_bounds():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=4, beam_width=3, levels=2, neighbors=8))
    res = planner.plan()
    s = res.best
    assert 20.0 <= s.sat_c <= 26.0
    assert 4.8 <= s.flow_kg_s <= 13.8
    assert 13.0 <= s.chwst_c <= 19.0


def test_coarse_grid_subsample_is_unbiased():
    # grid**3 (1000) > max_evals (100): the subsample must span the full SAT range,
    # not just the lexicographic head.
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=10, beam_width=3, levels=0, max_evals=100))
    planner.plan()
    sats = {round(s.sat_c, 3) for s in ev.evaluated}
    assert min(sats) <= 21.0 and max(sats) >= 25.0
    assert len(ev.evaluated) <= 100


def test_default_neighbors_includes_diagonals():
    from planner.beam_search import BeamConfig
    assert BeamConfig().neighbors == 8


from planner.calibrator import Calibration


def test_energy_bias_corrects_predicted_kpi_same_winner():
    cfg = BeamConfig(grid=3, beam_width=3, levels=1)
    base = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface()),
                       ObjectiveWeights(), cfg).plan()
    cal = Calibration(bias={"total_hvac_energy_kwh": 50.0}, sigma={}, n_weeks=1, version="weeks-1")
    calibrated = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface()),
                             ObjectiveWeights(), cfg, calibration=cal).plan()
    # constant energy offset -> same optimal setpoints, predicted energy shifted by +50
    assert calibrated.best == base.best
    assert calibrated.best_kpi.total_hvac_energy_kwh == base.best_kpi.total_hvac_energy_kwh + 50.0
    assert calibrated.feasible == base.feasible


def test_planner_without_calibration_unchanged():
    res = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface()), ObjectiveWeights(),
                      BeamConfig(grid=3, beam_width=2, levels=1)).plan()   # no calibration arg
    assert res.feasible


def test_inlet_bias_steers_search_under_cap():
    # A large learned inlet bias must reach the feasibility gate: the corrected
    # winner's peak inlet respects the 26 C cap (safety, not just display). This
    # FAILS if apply() corrects the displayed inlet but not the violation flag.
    from planner.calibrator import Calibration
    cfg = BeamConfig(grid=4, beam_width=3, levels=1)
    cal = Calibration(bias={"inlet_temp_max_c": 4.0}, sigma={}, n_weeks=1, version="weeks-1")
    res = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface()),
                      ObjectiveWeights(), cfg, calibration=cal).plan()
    assert res.feasible                                  # a cooler feasible point exists
    assert res.best_kpi.inlet_violation_steps == 0
    assert res.best_kpi.inlet_temp_max <= 26.0 + 1e-9   # corrected inlet respects the cap


def test_plan_exposes_beam_finalists():
    ev = MockEvaluator(MockSurface())
    cfg = BeamConfig(grid=3, beam_width=4, levels=1)
    res = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(), cfg).plan()
    assert hasattr(res, "beam_finalists")
    assert 1 <= len(res.beam_finalists) <= 4
    s0, k0, sc0 = res.beam_finalists[0]
    assert (s0, k0, sc0) == (res.best, res.best_kpi, res.best_score)
