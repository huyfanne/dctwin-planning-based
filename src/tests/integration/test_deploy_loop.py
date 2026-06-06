import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"
FC = "models/forecaster.pkl"
IDF = "models/idf/building.idf"


@pytest.mark.skipif(
    not (Path(DT).exists() and Path(FC).exists() and Path(IDF).exists()),
    reason="model assets / IDF / fitted forecaster not present",
)
def test_perturbed_plant_deploy_records_realized(tmp_path):
    """1-day deploy against the perturbed plant; realized KPIs are captured."""
    import pickle
    import pandas as pd
    from planner.plant import DEFAULT_PLANT, build_plant_prototxt
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.forecaster import StatisticalForecaster
    from planner.types import Setpoints

    fc_cfg = pickle.loads(Path(FC).read_bytes())
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    forecast = forecaster.forecast(date(2013, 11, 11), 1 * 24 * 4)

    sp = Setpoints(sat_c=20.0, flow_kg_s=7.05, chwst_c=13.0)

    plant_proto = build_plant_prototxt(DT, DEFAULT_PLANT,
                                       str(tmp_path / "plant"))
    plant = ParallelEnvOracle(
        base_prototxt=plant_proto, project_root=".",
        config=OracleConfig(n_workers=1, timesteps_per_hour=4,
                            log_root=str(tmp_path / "plant_oracle")))
    realized = plant.evaluate([sp], forecast=forecast)[0]

    assert realized.total_hvac_energy_kwh > 0
    assert realized.inlet_temp_max == realized.inlet_temp_max  # not NaN
