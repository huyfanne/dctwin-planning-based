from planner.mock_evaluator import MockSurface, MockEvaluator
from planner.types import Setpoints


def test_energy_minimized_at_optimum():
    ev = MockEvaluator(MockSurface(sat_opt=24.0, flow_opt=8.0, chwst_opt=17.0,
                                   energy_base=100.0, inlet_cap=999.0))
    at_opt = ev.evaluate([Setpoints(24.0, 8.0, 17.0)])[0]
    off_opt = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    assert at_opt.total_hvac_energy_kwh == 100.0
    assert off_opt.total_hvac_energy_kwh > at_opt.total_hvac_energy_kwh


def test_inlet_rises_with_sat_and_chwst_falls_with_flow():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    cool = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    hot = ev.evaluate([Setpoints(26.0, 4.8, 19.0)])[0]
    assert hot.inlet_temp_max > cool.inlet_temp_max


def test_violation_flagged_above_cap():
    ev = MockEvaluator(MockSurface(inlet_cap=22.0))
    hot = ev.evaluate([Setpoints(26.0, 4.8, 19.0)])[0]
    cool = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    assert hot.inlet_violation_steps > 0
    assert cool.inlet_violation_steps == 0


def test_deterministic_and_batched():
    ev = MockEvaluator()
    a = ev.evaluate([Setpoints(23.0, 9.0, 16.0), Setpoints(24.0, 8.0, 17.0)])
    b = ev.evaluate([Setpoints(23.0, 9.0, 16.0), Setpoints(24.0, 8.0, 17.0)])
    assert len(a) == 2
    assert a[0].total_hvac_energy_kwh == b[0].total_hvac_energy_kwh
    assert ev.call_count == 2
    assert len(ev.evaluated) == 4


def test_mock_evaluate_schedules_constant_matches_single_kpi():
    from planner.mock_evaluator import MockEvaluator, MockSurface
    from planner.schedule import WeeklySchedule, DEFAULT_BLOCKS
    from planner.types import Setpoints
    ev = MockEvaluator(MockSurface())
    sp = Setpoints(24.0, 8.0, 17.0)
    single = ev.evaluate([sp])[0]
    sched = WeeklySchedule(DEFAULT_BLOCKS, (sp, sp))           # constant schedule
    sk = ev.evaluate_schedules([sched])[0]
    assert abs(sk.total_hvac_energy_kwh - single.total_hvac_energy_kwh) < 1e-9
    assert abs(sk.inlet_temp_max - single.inlet_temp_max) < 1e-9
