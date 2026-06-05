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


def _pool_good(task):
    from planner.types import WeeklyKPI
    return WeeklyKPI(total_hvac_energy_kwh=100.0 + task.candidate[0], pue_mean=1.2,
                     inlet_temp_max=24.0, inlet_violation_steps=0,
                     rh_violation_steps=0, feasible=True)


def _pool_slow(task):
    import time
    time.sleep(2.0)
    from planner.types import WeeklyKPI
    return WeeklyKPI(0.0, 1.0, 0.0, 0, 0, True)


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


def test_tasks_use_absolute_log_dir_and_bcvtb_host(monkeypatch, tmp_path):
    # Docker volume mounts need absolute paths; the EnergyPlus container needs a
    # reachable BCVTB host. Both must reach the worker via the EvalTask.
    import os
    captured = {}

    def _capture(task):
        captured["log_dir"] = task.log_dir
        captured["bcvtb_host"] = task.bcvtb_host
        captured["week_cfg"] = task.week_config_path
        return _good_kpi(task)

    monkeypatch.setattr(oracle_mod, "evaluate_one", _capture)
    _stub_week_config(monkeypatch)
    orc = ParallelEnvOracle(
        "base.prototxt",
        config=OracleConfig(use_process_pool=False, log_root="relative/logs",
                            bcvtb_host="172.17.0.1"),
    )
    orc.evaluate([Setpoints(22.0, 8.0, 17.0)], forecast=_FakeForecast(tmp_path))
    assert os.path.isabs(captured["log_dir"])
    assert captured["bcvtb_host"] == "172.17.0.1"


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


def test_process_pool_preserves_order(monkeypatch, tmp_path):
    _stub_week_config(monkeypatch)
    orc = ParallelEnvOracle("ignored.prototxt", worker_fn=_pool_good,
                            config=OracleConfig(n_workers=2, use_process_pool=True,
                                                log_root=str(tmp_path)))
    out = orc.evaluate([Setpoints(20.0, 8.0, 17.0), Setpoints(26.0, 8.0, 17.0)],
                       forecast=_FakeForecast(tmp_path))
    assert [round(k.total_hvac_energy_kwh) for k in out] == [120, 126]


def test_process_pool_timeout_marks_infeasible(monkeypatch, tmp_path):
    _stub_week_config(monkeypatch)
    orc = ParallelEnvOracle("ignored.prototxt", worker_fn=_pool_slow,
                            config=OracleConfig(n_workers=1, use_process_pool=True,
                                                timeout_s=0.1, log_root=str(tmp_path)))
    out = orc.evaluate([Setpoints(22.0, 8.0, 17.0)], forecast=_FakeForecast(tmp_path))
    assert out[0].feasible is False
