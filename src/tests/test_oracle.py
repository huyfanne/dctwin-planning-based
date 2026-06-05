from pathlib import Path

from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.kpi import OracleSettings
from planner.types import Setpoints, WeeklyKPI
import planner.oracle as oracle_mod


def _good_kpi(task):
    sat = task.candidate[0]
    return WeeklyKPI(total_hvac_energy_kwh=100.0 + sat, pue_mean=1.2,
                     inlet_temp_max=24.0, inlet_violation_steps=0,
                     rh_violation_steps=0, feasible=True)


class _FakeForecast:
    def __init__(self, tmp_path):
        self.week_start = __import__("datetime").date(2013, 11, 11)
        self.materialized = False
        self._tmp = tmp_path
    def materialize(self, project_root):
        self.materialized = True


def _stub_week_config(monkeypatch):
    # avoid the real write_week_config (which imports dctwin)
    monkeypatch.setattr(oracle_mod, "write_week_config",
                        lambda base, ws, out, **k: out)


def test_returns_one_kpi_per_candidate_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(oracle_mod, "evaluate_one", _good_kpi)
    _stub_week_config(monkeypatch)
    orc = ParallelEnvOracle(
        base_prototxt="ignored.prototxt",
        config=OracleConfig(n_workers=1, use_process_pool=False,
                            log_root=str(tmp_path), timesteps_per_hour=4),
    )
    cands = [Setpoints(20.0, 8.0, 17.0), Setpoints(26.0, 8.0, 17.0)]
    out = orc.evaluate(cands, forecast=_FakeForecast(tmp_path))
    assert len(out) == 2
    assert out[0].total_hvac_energy_kwh == 120.0
    assert out[1].total_hvac_energy_kwh == 126.0


def test_worker_exception_becomes_infeasible(monkeypatch, tmp_path):
    def boom(task):
        raise RuntimeError("docker died")
    monkeypatch.setattr(oracle_mod, "evaluate_one", boom)
    _stub_week_config(monkeypatch)
    orc = ParallelEnvOracle(
        base_prototxt="ignored.prototxt",
        config=OracleConfig(n_workers=1, use_process_pool=False, log_root=str(tmp_path)),
    )
    out = orc.evaluate([Setpoints(22.0, 8.0, 17.0)], forecast=_FakeForecast(tmp_path))
    assert out[0].feasible is False


def test_materializes_forecast(monkeypatch, tmp_path):
    monkeypatch.setattr(oracle_mod, "evaluate_one", _good_kpi)
    _stub_week_config(monkeypatch)
    fc = _FakeForecast(tmp_path)
    orc = ParallelEnvOracle(base_prototxt="ignored.prototxt",
                            config=OracleConfig(use_process_pool=False, log_root=str(tmp_path)))
    orc.evaluate([Setpoints(22.0, 8.0, 17.0)], forecast=fc)
    assert fc.materialized is True
