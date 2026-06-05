import datetime
from pathlib import Path

import pytest

from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.kpi import OracleSettings
from planner.types import Setpoints

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"


@pytest.mark.skipif(not Path(DT).exists(), reason="model assets not copied into src/")
def test_single_candidate_short_window(tmp_path):
    orc = ParallelEnvOracle(
        base_prototxt=DT,
        config=OracleConfig(n_workers=1, use_process_pool=False,
                            log_root=str(tmp_path), timesteps_per_hour=4,
                            settings=OracleSettings()),
    )

    class _F:
        week_start = datetime.date(2013, 11, 11)
        def materialize(self, root):  # workloads already on disk from the GDS copy
            pass

    from planner import week_config
    orig = week_config.compute_week_period
    week_config.compute_week_period = lambda ws, days=7: orig(ws, days=1)
    try:
        out = orc.evaluate([Setpoints(24.0, 8.0, 18.0)], forecast=_F())
    finally:
        week_config.compute_week_period = orig

    kpi = out[0]
    assert kpi.feasible
    assert kpi.total_hvac_energy_kwh > 0
    assert kpi.inlet_temp_max > 0


@pytest.mark.skipif(not Path(DT).exists(), reason="model assets not copied into src/")
def test_two_candidates_parallel_processes(tmp_path):
    orc = ParallelEnvOracle(
        base_prototxt=DT,
        config=OracleConfig(n_workers=2, use_process_pool=True,
                            log_root=str(tmp_path), timesteps_per_hour=4),
    )

    class _F:
        week_start = datetime.date(2013, 11, 11)
        def materialize(self, root):
            pass

    from planner import week_config
    orig = week_config.compute_week_period
    week_config.compute_week_period = lambda ws, days=7: orig(ws, days=1)
    try:
        out = orc.evaluate([Setpoints(22.0, 10.0, 16.0), Setpoints(25.0, 6.0, 19.0)], forecast=_F())
    finally:
        week_config.compute_week_period = orig

    assert len(out) == 2
    assert all(k.feasible for k in out)
    assert out[0].total_hvac_energy_kwh != out[1].total_hvac_energy_kwh
