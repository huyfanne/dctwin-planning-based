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
    # Legacy calibration (no sigma_post) falls back to the floor-pinned sigma: at the
    # prior it CAPS at base — never widens past it (the old bug doubled it to 0.2 and
    # deadlocked the gate after the first deploy).
    assert scenario_spread(Calibration({}, {"inlet_temp_max_c": 1.0}, 1, "weeks-1"),
                           base_spread=0.1, sigma_ref=1.0) == 0.1
    # With the empirical-Bayes posterior, ONE accurate measured week tightens the
    # bracket by sqrt(2) — modest, evidence-proportional.
    one_week = Calibration({}, {"inlet_temp_max_c": 1.0}, 1, "weeks-1",
                           sigma_post={"inlet_temp_max_c": 0.7071})
    assert abs(scenario_spread(one_week) - 0.07071) < 1e-4
    # The bracket never collapses below the physical drift floor, however accurate...
    nine = Calibration({}, {"inlet_temp_max_c": 0.05}, 9, "weeks-9",
                       sigma_post={"inlet_temp_max_c": 0.05})
    assert scenario_spread(nine) == 0.02
    # ...and never exceeds the cold-start base, however bad the residuals look.
    wild = Calibration({}, {"inlet_temp_max_c": 5.0}, 2, "weeks-2",
                       sigma_post={"inlet_temp_max_c": 5.0})
    assert scenario_spread(wild) == 0.1


def test_rerank_scenario_check_is_hard_cap_not_margined(tmp_path, monkeypatch):
    """Single-counting: a scenario inlet of 25.5 C is BELOW the hard 26 cap in a plant
    that is already physically degraded — it must pass even when the nominal weights
    carry the full cold-start k*sigma margin (which alone would demand <= 25.0)."""
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank
    from planner.oracle import OracleConfig
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass

        def evaluate(self, candidates, forecast=None, on_result=None):
            return [_kpi(100.0, 25.5) for _ in candidates]

    sp = Setpoints(24, 8, 17)
    margined = ObjectiveWeights(inlet_forecast_margin=1.0)   # nominal cold-start margin
    fn = make_oracle_robust_rerank(
        base_prototxt="p", oracle_config=OracleConfig(n_workers=1, log_root=str(tmp_path)),
        calibration=None, weights=margined, n_scenarios=2,
        log_root=str(tmp_path), oracle_cls=_Oracle)
    rr = fn([(sp, _kpi(100, 25.5), 100.0)], forecast=None)
    assert rr.robust_feasible is True


def test_rerank_applies_measured_bias_to_scenarios(tmp_path, monkeypatch):
    """The MEASURED bias is single-counted into each scenario: a +0.7 C under-prediction
    pushes a 25.6 C scenario to 26.3 C — over the hard cap -> not robust-feasible."""
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank
    from planner.oracle import OracleConfig
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass

        def evaluate(self, candidates, forecast=None, on_result=None):
            return [_kpi(100.0, 25.6) for _ in candidates]

    cal = Calibration(bias={"inlet_temp_max_c": 0.7}, sigma={"inlet_temp_max_c": 1.0},
                      n_weeks=1, version="weeks-1")
    sp = Setpoints(24, 8, 17)
    fn = make_oracle_robust_rerank(
        base_prototxt="p", oracle_config=OracleConfig(n_workers=1, log_root=str(tmp_path)),
        calibration=cal, weights=ObjectiveWeights(), n_scenarios=2,
        log_root=str(tmp_path), oracle_cls=_Oracle)
    rr = fn([(sp, _kpi(100, 25.6), 100.0)], forecast=None)
    assert rr.robust_feasible is False


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
    # buys margin along the CHEAP axis first: chilled-water-only variants that KEEP the
    # optimum's low (cheap) airflow — colder water restores degraded-coil capacity without
    # paying the ~15% fan-energy premium of the corner diagonal
    assert any(v.flow_kg_s == best.flow_kg_s and v.chwst_c < best.chwst_c
               and v.sat_c == best.sat_c for v in ladder)
    # ...and chw+SAT variants still at the optimum's airflow
    assert any(v.flow_kg_s == best.flow_kg_s and v.chwst_c < best.chwst_c
               and v.sat_c < best.sat_c for v in ladder)


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


def _capture_rerank_centers(tmp_path, monkeypatch, plant_config_path):
    """Run a 3-scenario rerank capturing the PlantConfig of each scenario; the middle
    scenario of an odd ensemble IS the center (make_scenarios multiplier 1.0)."""
    import planner.robust as R
    captured = []

    def fake_build(base, plant, out_dir):
        captured.append(plant)
        return f"{out_dir}/plant.prototxt"

    monkeypatch.setattr(R, "build_plant_prototxt", fake_build)
    sp = Setpoints(24, 8, 17)
    fn = make_oracle_robust_rerank(
        base_prototxt="p", oracle_config=OracleConfig(n_workers=1, log_root=str(tmp_path)),
        calibration=None, weights=ObjectiveWeights(), n_scenarios=3,
        log_root=str(tmp_path), oracle_cls=_FakeOracle,
        plant_config_path=plant_config_path)
    fn([(sp, _kpi(100, 24), 100.0)], forecast=None)
    return captured


def test_rerank_center_defaults_to_default_plant_without_calibration_file(tmp_path, monkeypatch):
    # #9 no-behavior-change proof: absent plant_calibration.json -> the ensemble
    # center is DEFAULT_PLANT exactly.
    captured = _capture_rerank_centers(tmp_path, monkeypatch, str(tmp_path / "absent.json"))
    assert len(captured) == 3
    assert captured[1] == DEFAULT_PLANT


def test_rerank_center_is_data_driven_when_calibration_file_present(tmp_path, monkeypatch):
    # #9: the deploy loop's fitted fan factor replaces the matching DEFAULT_PLANT
    # perturbation in the ensemble center; the coil perturbation is kept.
    import json
    cfg_path = tmp_path / "plant_calibration.json"
    cfg_path.write_text(json.dumps({"perturbations": [
        {"table": "Fan_VariableVolume", "field": "fan_total_efficiency", "factor": 0.9}],
        "basis": {"n_weeks": 4}}))
    captured = _capture_rerank_centers(tmp_path, monkeypatch, str(cfg_path))
    center = captured[1]
    by_key = {(p.table, p.field): p.factor for p in center.perturbations}
    assert by_key[("Fan_VariableVolume", "fan_total_efficiency")] == 0.9
    assert by_key[("Coil_Cooling_Water", "design_water_flow_rate")] == 0.85


def test_rerank_adds_hot_weather_scenario_when_forecast_has_weather(tmp_path, monkeypatch):
    """Stage 6 #7: a forecast carrying a real EPW adds ONE hot-weather run (believed plant,
    dry-bulb +1*sigma) — weather uncertainty gates plans like plant uncertainty does."""
    import dataclasses
    from datetime import date
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank
    from planner.oracle import OracleConfig
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")
    # tiny EPW: header(8) + 3 weeks of hourly rows around Nov 8 (reuse the epw fixture style)
    rows = ["H%d" % i for i in range(7)] + ["DATA PERIODS,1,1,Data,Sunday, 11/ 1, 11/30"]
    for d in range(1, 22):
        for h in range(1, 25):
            rows.append(f"2024,11,{d},{h},0,C9,{28 + (d % 3):.1f},20.0,80,101325,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
    epw = tmp_path / "w.epw"; epw.write_text("\n".join(rows))

    @dataclasses.dataclass
    class _F:
        week_start: object
        weather_file: str

    seen = []

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass

        def evaluate(self, candidates, forecast=None, on_result=None):
            seen.append(getattr(forecast, "weather_file", None))
            return [_kpi(100.0, 24.0) for _ in candidates]

    fn = make_oracle_robust_rerank(
        base_prototxt="p", oracle_config=OracleConfig(n_workers=1, log_root=str(tmp_path)),
        calibration=None, weights=ObjectiveWeights(), n_scenarios=2,
        log_root=str(tmp_path), oracle_cls=_Oracle,
        plant_config_path=str(tmp_path / "absent.json"))
    rr = fn([(Setpoints(24, 8, 17), _kpi(100, 24), 100.0)],
            forecast=_F(week_start=date(2024, 11, 8), weather_file=str(epw)))
    assert rr.n_scenarios == 3                       # 2 plant + 1 hot-weather
    assert len(seen) == 3
    assert any(w and w != str(epw) for w in seen)    # the hot EPW variant was evaluated
    assert rr.robust_feasible is True


def test_rerank_no_weather_scenario_without_weather_file(tmp_path, monkeypatch):
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank
    from planner.oracle import OracleConfig
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass

        def evaluate(self, candidates, forecast=None, on_result=None):
            return [_kpi(100.0, 24.0) for _ in candidates]

    fn = make_oracle_robust_rerank(
        base_prototxt="p", oracle_config=OracleConfig(n_workers=1, log_root=str(tmp_path)),
        calibration=None, weights=ObjectiveWeights(), n_scenarios=2,
        log_root=str(tmp_path), oracle_cls=_Oracle,
        plant_config_path=str(tmp_path / "absent.json"))
    rr = fn([(Setpoints(24, 8, 17), _kpi(100, 24), 100.0)], forecast=None)
    assert rr.n_scenarios == 2                       # unchanged without weather
