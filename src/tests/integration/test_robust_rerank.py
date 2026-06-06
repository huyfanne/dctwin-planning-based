import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_robust_rerank_over_two_scenarios(tmp_path):
    """2-scenario robust re-rank of 2 finalists on a 1-day window (real EnergyPlus)."""
    import pickle
    import pandas as pd
    from planner.robust import make_oracle_robust_rerank, RobustResult
    from planner.forecaster import StatisticalForecaster
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    fc_cfg = pickle.loads(Path("models/forecaster.pkl").read_bytes())
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    forecast = forecaster.forecast(date(2013, 11, 11), 1 * 24 * 4)

    class _Cfg:
        n_workers = 1
        timesteps_per_hour = 4

    def _k():
        return WeeklyKPI(total_hvac_energy_kwh=0.0, pue_mean=1.2, inlet_temp_max=25.0,
                         inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                         inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)

    finalists = [(Setpoints(20.0, 7.05, 13.0), _k(), 0.0),
                 (Setpoints(22.0, 7.05, 14.0), _k(), 0.0)]
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt", _Cfg(), None,
                                   ObjectiveWeights(), n_scenarios=2, log_root=str(tmp_path))
    rr = fn(finalists, forecast=forecast)
    assert isinstance(rr, RobustResult) and rr.n_scenarios == 2
    assert rr.cvar_energy_kwh > 0
    assert "inlet_temp_max_c" in rr.confidence_bands
