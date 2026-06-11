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


def test_oracle_passes_weather_file_to_week_config(tmp_path, monkeypatch):
    import planner.oracle as O
    from planner.forecaster import Forecast
    from datetime import date

    captured = {}
    def fake_wwc(base, week_start, out_path, days=7, timesteps_per_hour=None, weather_file=None):
        captured["weather_file"] = weather_file
        return str(out_path)
    monkeypatch.setattr(O, "write_week_config", fake_wwc)

    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={}, method="seasonal",
                  weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")
    oracle = O.ParallelEnvOracle("configs/dt/dt.prototxt")
    oracle._write_week_cfg(fc, str(tmp_path / "w.prototxt"))
    assert captured["weather_file"] == "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"


def test_replay_with_trajectory_uses_sample_worker():
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.types import Setpoints, WeeklyKPI
    from planner.kpi import StepSample
    calls = {}
    fake_kpi = WeeklyKPI(total_hvac_energy_kwh=10.0, pue_mean=1.2, inlet_temp_max=24.0,
                         inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    fake_samples = [StepSample(total_power_w=1200.0, it_power_w=1000.0, inlet_temps=[24.0])]

    def fake_sample_worker(task):
        calls["candidate"] = task.candidate
        return fake_kpi, fake_samples

    orc = ParallelEnvOracle(base_prototxt="configs/dt/dt.prototxt",
                            config=OracleConfig(use_process_pool=False, log_root="log/test_replay"),
                            sample_worker_fn=fake_sample_worker)
    kpi, samples = orc.replay_with_trajectory(Setpoints(22.0, 7.0, 15.0), forecast=None)
    assert kpi is fake_kpi and samples is fake_samples
    assert calls["candidate"] == (22.0, 7.0, 15.0)


def test_batch_deadline_scales_with_waves_not_task_count():
    from planner.oracle import _batch_deadline
    assert _batch_deadline(10, 24, 4) == 10 * (6 + 1)   # ceil(24/4)=6 waves (+1 slack)
    assert _batch_deadline(10, 3, 4) == 10 * (1 + 1)    # fewer tasks than workers -> 1 wave
    assert _batch_deadline(10, 0, 4) == 10 * (1 + 1)    # n_tasks=0 guarded


def _hang_worker(task):
    import time
    from planner.oracle_worker import _infeasible
    time.sleep(3)                                       # never returns before the deadline
    return _infeasible("x")


def test_evaluate_bounds_a_hung_worker_by_the_deadline(tmp_path):
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.types import Setpoints
    import time
    cfg = OracleConfig(n_workers=2, timeout_s=0.3, use_process_pool=True,
                       log_root=str(tmp_path / "oracle"))
    oracle = ParallelEnvOracle("dummy.prototxt", config=cfg, worker_fn=_hang_worker)
    cands = [Setpoints(24.0, 8.0, 17.0) for _ in range(4)]
    t0 = time.time()
    results = oracle.evaluate(cands)
    elapsed = time.time() - t0
    assert len(results) == 4 and all(not r.feasible for r in results)   # hung -> infeasible
    assert elapsed < 2.5                                # bounded by the wave deadline (~0.9s), not 3s


def _pool_wedge_one(task):
    """Simulates a wedged candidate that defeats its own per-candidate watchdog
    (incident gds-2024-12-06-a368bc): candidate sat==99 never returns in time."""
    import time
    from planner.types import WeeklyKPI
    if task.candidate[0] >= 99.0:
        time.sleep(6.0)
    return WeeklyKPI(total_hvac_energy_kwh=100.0 + task.candidate[0], pue_mean=1.2,
                     inlet_temp_max=24.0, inlet_violation_steps=0,
                     rh_violation_steps=0, feasible=True)


def test_stalled_future_is_abandoned_within_stall_window(monkeypatch, tmp_path):
    """If nothing completes within ~1.5x timeout_s while futures are pending, the
    stragglers are abandoned as infeasible — the batch must NOT wait for the absolute
    waves-deadline (70 min in the real incident; here 7s vs the ~2s stall path)."""
    import time
    _stub_week_config(monkeypatch)
    fast = [Setpoints(20.0 + i * 0.5, 8.0, 17.0) for i in range(11)]   # sat 20..25
    wedged = Setpoints(99.0, 8.0, 17.0)
    orc = ParallelEnvOracle("ignored.prototxt", worker_fn=_pool_wedge_one,
                            config=OracleConfig(n_workers=2, use_process_pool=True,
                                                timeout_s=1.0, log_root=str(tmp_path)))
    t0 = time.monotonic()
    out = orc.evaluate(fast + [wedged], forecast=_FakeForecast(tmp_path))
    elapsed = time.monotonic() - t0
    # waves-deadline would be 1.0 * (ceil(12/2)+1) = 7s; the stall guard cuts out at
    # ~last-completion + 1.5s
    assert elapsed < 5.0, f"took {elapsed:.1f}s — stall guard did not fire"
    assert all(k.feasible for k in out[:-1])            # fast results all collected
    assert out[-1].feasible is False                    # the wedged one abandoned
