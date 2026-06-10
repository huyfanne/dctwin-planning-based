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


def test_scenario_spread_cold_start_and_tightens():
    # Cold start uses the conservative prior bracket.
    assert scenario_spread(None) == 0.1
    assert scenario_spread(Calibration({}, {}, 0, "weeks-0")) == 0.1
    # At the prior sigma (== sigma_ref) it must CAP at base — never widen past it (the old
    # bug doubled it to 0.2 here, deadlocking the gate after the first deploy).
    assert scenario_spread(Calibration({}, {"inlet_temp_max_c": 1.0}, 1, "weeks-1"),
                           base_spread=0.1, sigma_ref=1.0) == 0.1
    # As calibration confirms accuracy (sigma below the reference), the bracket TIGHTENS.
    assert scenario_spread(Calibration({}, {"inlet_temp_max_c": 0.5}, 4, "weeks-4"),
                           base_spread=0.1, sigma_ref=1.0) == 0.05
    assert scenario_spread(Calibration({}, {"inlet_temp_max_c": 0.0}, 9, "weeks-9"),
                           base_spread=0.1, sigma_ref=1.0) == 0.0


def test_safety_ladder_adds_cooling_within_bounds():
    from planner.robust import safety_ladder
    from planner.types import DEFAULT_SEARCH_SPACE as S, Setpoints
    best = Setpoints(23.0, 4.8, 19.0)            # fragile energy optimum: min flow, warm CHW
    ladder = safety_ladder(best, S)
    assert len(ladder) >= 3
    for v in ladder:
        # every variant adds cooling margin along at least one axis
        assert v.chwst_c < best.chwst_c or v.flow_kg_s > best.flow_kg_s or v.sat_c < best.sat_c
        # ...and stays within the search bounds
        assert S.sat.lb <= v.sat_c <= S.sat.ub
        assert S.flow.lb <= v.flow_kg_s <= S.flow.ub
        assert S.chwst.lb <= v.chwst_c <= S.chwst.ub
    # includes the guaranteed-safe max-cooling corner
    assert any(v.as_tuple() == (S.sat.lb, S.flow.ub, S.chwst.lb) for v in ladder)


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


from planner.robust import make_oracle_robust_rerank
from planner.oracle import OracleConfig


class _FakeOracle:
    instances = []

    def __init__(self, base_prototxt, config=None, project_root="."):
        self.base_prototxt = base_prototxt
        _FakeOracle.instances.append(base_prototxt)

    def evaluate(self, candidates, forecast=None, on_result=None):
        return [_kpi(100.0, 24.0) for _ in candidates]


def test_make_oracle_robust_rerank_runs_scenarios(tmp_path, monkeypatch):
    import planner.robust as R
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")
    _FakeOracle.instances = []
    sp = Setpoints(24, 8, 17)
    finalists = [(sp, _kpi(100, 24), 100.0)]
    fn = make_oracle_robust_rerank(
        base_prototxt="configs/dt/dt.prototxt",
        oracle_config=OracleConfig(n_workers=1, timesteps_per_hour=4, log_root=str(tmp_path)),
        calibration=None, weights=ObjectiveWeights(), n_scenarios=3,
        log_root=str(tmp_path), oracle_cls=_FakeOracle)
    rr = fn(finalists, forecast=None)
    assert rr.n_scenarios == 3
    assert len(_FakeOracle.instances) == 3
    assert rr.winner == sp


def test_robust_select_requires_majority_successful_scenarios():
    from planner.robust import robust_select
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    def k(inlet, energy=100.0, feasible=True):
        return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                         inlet_violation_steps=0 if feasible else 5, rh_violation_steps=0, feasible=True)

    finalists = [(Setpoints(22, 7, 15), k(24), 100.0, k(24))]
    # 4 scenarios requested, but only 1 succeeded (3 dropped) -> below ceil(4/2)=2 -> not robust-feasible
    scenario_kpis = [[k(24)]]
    res = robust_select(finalists, scenario_kpis, ObjectiveWeights(), n_requested=4)
    assert res.robust_feasible is False
    assert res.scenarios_ok == 1


def test_robust_select_majority_present_is_feasible():
    from planner.robust import robust_select
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    def k(inlet):
        return WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=inlet,
                         inlet_violation_steps=0, rh_violation_steps=0, feasible=True)

    finalists = [(Setpoints(22, 7, 15), k(24), 100.0, k(24))]
    scenario_kpis = [[k(24), k(25), k(24)]]   # 3 of 4 succeeded, all feasible
    res = robust_select(finalists, scenario_kpis, ObjectiveWeights(), n_requested=4)
    assert res.robust_feasible is True
    assert res.scenarios_ok == 3
