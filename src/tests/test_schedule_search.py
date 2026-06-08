from planner.schedule_search import refine_schedule
from planner.schedule import WeeklySchedule, DEFAULT_BLOCKS
from planner.objective import ObjectiveWeights
from planner.types import Setpoints
from planner.kpi import WeeklyKPI    # noqa: F401


class _Monotone:
    """Schedule evaluator where warmer SAT / lower flow is CHEAPER but raises inlet. The DAY
    block (index 0, ambient 22 C) is near its inlet limit at the constant, so it can't relax;
    the NIGHT block (index 1, ambient 19 C = 3 C cooler) has slack — so the optimum is a SPLIT
    where the night block is relaxed (here greedy coordinate-descent relaxes night FLOW, since
    that is the steepest energy lever on this surface; day can't because lower flow breaches)."""
    CAP = 26.0
    def evaluate_schedules(self, schedules, forecast=None):
        from planner.types import WeeklyKPI
        out = []
        for sch in schedules:
            tot_e, max_inlet, viol = 0.0, -1e9, 0
            for b, sp in enumerate(sch.setpoints):
                ambient = 22.0 - (3.0 if b == 1 else 0.0)   # day 22, night 19
                inlet = ambient + 1.0 * (sp.sat_c - 20) + 0.5 * (sp.chwst_c - 13) - 0.4 * (sp.flow_kg_s - 4.8)
                energy = 200.0 - 5 * (sp.sat_c - 20) - 3 * (sp.chwst_c - 13) + 4 * (sp.flow_kg_s - 4.8)
                tot_e += energy / len(sch.setpoints)
                max_inlet = max(max_inlet, inlet)
                viol += 0 if inlet <= self.CAP else 1
            out.append(WeeklyKPI(total_hvac_energy_kwh=tot_e, pue_mean=1.2, inlet_temp_max=max_inlet,
                                 inlet_violation_steps=viol, rh_violation_steps=0, feasible=True,
                                 inlet_excess_degc_steps=max(max_inlet - (self.CAP - 1), 0.0)))
        return out


def test_refine_schedule_finds_a_cheaper_night_relaxed_split():
    const = Setpoints(23.0, 8.0, 17.0)        # day inlet 25.72 <= 26 (near limit), night 22.72 (slack)
    ev = _Monotone()
    const_energy = ev.evaluate_schedules(
        [WeeklySchedule(DEFAULT_BLOCKS, (const, const))])[0].total_hvac_energy_kwh
    res = refine_schedule(const, ev, ObjectiveWeights(), forecast=None, calibration=None, levels=2)
    day_sp, night_sp = res.schedule.setpoints
    # the cooler night block gets relaxed (the day block is inlet-constrained at the constant and can't).
    # WHICH control relaxes depends on the surface, so assert a genuine, strictly-cheaper split.
    assert night_sp != day_sp                                    # genuine day/night split
    assert res.kpi.total_hvac_energy_kwh < const_energy          # strictly cheaper than the constant


def test_refine_schedule_never_worse_than_constant_on_flat_surface():
    const = Setpoints(24.0, 8.0, 17.0)

    class _Flat:
        def evaluate_schedules(self, schedules, forecast=None):
            from planner.types import WeeklyKPI
            return [WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=22.0,
                              inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                              inlet_excess_degc_steps=0.0) for _ in schedules]

    res = refine_schedule(const, _Flat(), ObjectiveWeights(), forecast=None, calibration=None, levels=2)
    # flat surface -> no improvement -> the seed (constant, constant) is returned
    assert res.schedule.setpoints[0] == const and res.schedule.setpoints[1] == const
