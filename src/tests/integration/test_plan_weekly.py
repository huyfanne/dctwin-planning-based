import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"
FC = "models/forecaster.pkl"


@pytest.mark.skipif(not (Path(DT).exists() and Path(FC).exists()),
                    reason="model assets / fitted forecaster not present")
def test_tiny_weekly_plan_then_baseline_acceptance(tmp_path, monkeypatch):
    # shrink the planning window to 1 day for speed; grid=3/levels=1 is the
    # smallest search verified to find a feasible, energy-reducing plan.
    from planner import week_config
    orig = week_config.compute_week_period
    monkeypatch.setattr(week_config, "compute_week_period",
                        lambda ws, days=7: orig(ws, days=1))

    from plan_weekly import WeeklyPlanTemplate
    WeeklyPlanTemplate()(
        dt_engine_config=DT, forecaster_config=FC,
        week_start=date(2013, 11, 11), days=1,
        grid=3, beam_width=3, levels=1, n_workers=8,
    )

    rec = json.loads(Path("log/recommendation.json").read_text())
    assert rec["status"] in ("pending_approval", "infeasible_fallback")
    assert set(rec["setpoints"]) == {
        "crah_supply_air_temperature_c",
        "crah_supply_air_mass_flow_rate_kg_s",
        "chilled_water_supply_temperature_c",
    }

    # ACCEPTANCE: recommended plan must be feasible (0 inlet violations) and
    # use less HVAC energy than the conservative baseline.
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.types import DEFAULT_SEARCH_SPACE as S, Setpoints

    class _F:
        week_start = date(2013, 11, 11)
        def materialize(self, root): pass

    orc = ParallelEnvOracle(base_prototxt=DT,
                            config=OracleConfig(n_workers=2, use_process_pool=True,
                                                log_root=str(tmp_path / "acc")))
    rec_sp = rec["setpoints"]
    plan_sp = Setpoints(rec_sp["crah_supply_air_temperature_c"],
                        rec_sp["crah_supply_air_mass_flow_rate_kg_s"],
                        rec_sp["chilled_water_supply_temperature_c"])
    baseline_sp = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)
    plan_kpi, base_kpi = orc.evaluate([plan_sp, baseline_sp], forecast=_F())

    assert plan_kpi.feasible and base_kpi.feasible
    assert plan_kpi.inlet_violation_steps == 0
    assert plan_kpi.total_hvac_energy_kwh < base_kpi.total_hvac_energy_kwh
