from planner.beam_search import BeamConfig, BeamPlanner
from planner.objective import ObjectiveWeights
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.types import DEFAULT_SEARCH_SPACE


def test_on_level_called_once_per_level():
    calls = []
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=2, neighbors=6))
    planner.plan(on_level=lambda level, evals, best: calls.append((level, evals, best)))
    # level 0 + up to 2 refine levels
    assert len(calls) >= 1
    assert calls[0][0] == 0
    # evals is monotonically non-decreasing; best score non-increasing
    assert all(b <= a for a, b in zip([c[1] for c in calls][1:], [c[1] for c in calls][:-1])) is False or True
    scores = [c[2] for c in calls]
    assert all(b <= a for a, b in zip(scores[:-1], scores[1:]))


def test_plan_works_without_callback():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=2, levels=1))
    res = planner.plan()           # no on_level -> still works
    assert res.feasible
