import pytest
from datetime import date

from planner.week_config import compute_week_period, WeekPeriod, write_week_config
from dctwin.utils import read_engine_config


def test_week_period_inclusive_seven_days():
    p = compute_week_period(date(2013, 11, 11), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=11, end_month=11, end_day=17)


def test_week_period_crosses_month():
    p = compute_week_period(date(2013, 11, 28), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=28, end_month=12, end_day=4)


def test_week_period_rejects_year_wrap():
    with pytest.raises(ValueError):
        compute_week_period(date(2013, 12, 30), days=7)


def test_write_week_config_sets_weather_file(tmp_path):
    out = tmp_path / "week.prototxt"
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7,
                      weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")
    cfg = read_engine_config(str(out))
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert env.weather_file == "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"
    assert env.simulation_time_config.begin_month == 11
    assert env.simulation_time_config.begin_day_of_month == 11


def test_write_week_config_rejects_week_outside_epw_coverage(tmp_path):
    out = tmp_path / "week.prototxt"
    with pytest.raises(ValueError, match="outside the weather file coverage"):
        write_week_config("configs/dt/dt.prototxt", date(2024, 6, 1), str(out), days=7,
                          weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")


def test_write_week_config_without_weather_file_unchanged(tmp_path):
    out = tmp_path / "week.prototxt"
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7)
    cfg = read_engine_config(str(out))
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert env.weather_file.endswith("IWEC.epw")


def test_write_week_config_lifts_acu_masking(tmp_path):
    """The controlled hall's AGENT_CONTROLLED actuators have their on/off masking removed
    by default, so the planner's setpoints are always applied."""
    from dctwin.utils import read_engine_config
    out = tmp_path / "week.prototxt"
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7)
    cfg = read_engine_config(str(out))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    masked = [a for a in env_cfg.actions if a.control_type == 2 and a.masking_variable_name]
    assert masked == []


def test_write_week_config_can_keep_acu_masking(tmp_path):
    from dctwin.utils import read_engine_config
    out = tmp_path / "week.prototxt"
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7,
                      lift_acu_masking=False)
    cfg = read_engine_config(str(out))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    masked = [a for a in env_cfg.actions if a.control_type == 2 and a.masking_variable_name]
    assert len(masked) == 44   # original GDS 1F-2A config: 22 SAT + 22 flow masked
