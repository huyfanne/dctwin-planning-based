import json
import pickle
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"
FC = "models/forecaster.pkl"
REAL_EPW = "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"


@pytest.mark.skipif(
    not (Path(DT).exists() and Path(FC).exists() and Path(REAL_EPW).exists()),
    reason="model assets / fitted forecaster / real EPW not present",
)
def test_oracle_runs_on_real_weather_within_year(tmp_path):
    """EnergyPlus oracle runs a 1-day window using the real provided EPW (Nov 2024).

    Asserts:
    - The written per-week prototxt references the Singapore_Changi EPW.
    - The oracle returns exactly 1 KPI with total_hvac_energy_kwh >= 0.
    """
    from planner.forecaster import build_forecaster
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.types import Setpoints

    # Load the fitted forecaster config (mirrors test_deploy_loop.py pkl-load pattern)
    fc_cfg = pickle.loads(Path(FC).read_bytes())
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())

    # Build the forecaster with the REAL EPW injected (FB Task 6)
    forecaster = build_forecaster(
        fc_cfg["method"],
        his,
        room2ite,
        fc_cfg["his_col_for_room"],
        weather_file=REAL_EPW,
    )

    # 1-day window; date(2024, 11, 11) is within the EPW's Nov 2024 – Jan 2025 range
    n_steps = 1 * 24 * 4
    forecast = forecaster.forecast(date(2024, 11, 11), n_steps)

    assert forecast.weather_file == REAL_EPW, (
        f"Forecast.weather_file must be the real EPW; got {forecast.weather_file!r}"
    )

    log_root = str(tmp_path / "oracle")
    oracle = ParallelEnvOracle(
        base_prototxt=DT,
        project_root=".",
        config=OracleConfig(
            n_workers=1,
            timesteps_per_hour=4,
            log_root=log_root,
        ),
    )
    kpis = oracle.evaluate([Setpoints(sat_c=22.0, flow_kg_s=7.05, chwst_c=14.0)],
                           forecast=forecast)

    assert len(kpis) == 1, f"Expected 1 KPI result, got {len(kpis)}"
    assert kpis[0].total_hvac_energy_kwh >= 0.0, (
        f"total_hvac_energy_kwh must be non-negative; got {kpis[0].total_hvac_energy_kwh}"
    )

    # The oracle writes the per-week prototxt at log_root/week.prototxt
    # (oracle.py: week_cfg_path = str(log_root / "week.prototxt"))
    written = list(Path(log_root).rglob("*.prototxt"))
    assert written, "Expected at least one *.prototxt under the oracle log_root"
    assert any("Singapore_Changi" in p.read_text() for p in written), (
        f"Per-week prototxt must reference the real EPW (Singapore_Changi). "
        f"Files found: {[str(p) for p in written]}"
    )
