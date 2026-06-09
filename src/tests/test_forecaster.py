import json
from datetime import date

import numpy as np
import pandas as pd

from planner.forecaster import (
    loading_from_it_loads, persistence_window, StatisticalForecaster, Forecast,
    seasonal_climatology, calendar_level_scale,
)


def test_loading_from_it_loads_divides_by_capacity_kw():
    s = pd.Series([2000.0, 1000.0])
    out = loading_from_it_loads(s, total_watts=4_000_000.0)
    np.testing.assert_allclose(out.to_numpy(), [0.5, 0.25])


def test_persistence_window_takes_last_n_steps():
    s = pd.Series(list(range(100)), dtype=float)
    win = persistence_window(s, n_steps=10)
    assert list(win) == list(range(90, 100))


def test_persistence_window_tiles_when_history_short():
    s = pd.Series([0.3, 0.4], dtype=float)
    win = persistence_window(s, n_steps=5)
    assert len(win) == 5
    assert set(np.round(win, 1)).issubset({0.3, 0.4})


def test_forecaster_writes_workload_arrays(tmp_path):
    df = pd.DataFrame({
        "1F_Datahall 2A 1F Data Hall 2A IT loads": [900.0] * 8,
    })
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    his_col_for_room = {"Data Hall 1F 2A": "1F_Datahall 2A 1F Data Hall 2A IT loads"}
    fc = StatisticalForecaster(df, room2ite, his_col_for_room, method="persistence")

    forecast = fc.forecast(week_start=date(2013, 11, 11), n_steps=4)
    assert isinstance(forecast, Forecast)
    arr = forecast.workload_schedules["Data Hall 1F 2A ite-1"]
    assert len(arr) == 4
    np.testing.assert_allclose(arr, [0.5, 0.5, 0.5, 0.5])

    forecast.materialize(project_root=str(tmp_path))
    written = json.loads(
        (tmp_path / "data/schedule/workloads/data hall 1f 2a ite-1.json").read_text()
    )
    assert written == [0.5, 0.5, 0.5, 0.5]


def test_forecast_carries_optional_bands():
    fc = Forecast(week_start=date(2024, 11, 11),
                  workload_schedules={"ite-1": [0.5, 0.5]},
                  method="seasonal",
                  bands={"ite-1": {"p10": [0.4, 0.4], "p50": [0.5, 0.5], "p90": [0.6, 0.6]}})
    assert fc.bands["ite-1"]["p90"] == [0.6, 0.6]


def test_forecast_bands_default_none():
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]})
    assert fc.bands is None


def test_seasonal_climatology_captures_diurnal_shape():
    times = pd.date_range("2024-11-04 00:00", periods=3 * 7 * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    loading = pd.Series(np.where(day, 0.8, 0.2), index=range(len(times)))
    point, bands = seasonal_climatology(loading, pd.Series(times.astype(str)),
                                        week_start=date(2024, 12, 2), n_steps=96, freq_min=15)
    assert len(point) == 96 and set(bands) == {"p10", "p50", "p90"}
    assert point[40] > 0.7 and point[4] < 0.3        # 10:00 daytime high, 01:00 night low
    assert np.all(bands["p10"] <= bands["p50"]) and np.all(bands["p50"] <= bands["p90"])


def test_seasonal_climatology_thin_bucket_falls_back():
    times = pd.date_range("2024-11-04 00:00", periods=2 * 96, freq="15min", tz="Asia/Singapore")
    loading = pd.Series(np.full(len(times), 0.5), index=range(len(times)))
    point, bands = seasonal_climatology(loading, pd.Series(times.astype(str)),
                                        week_start=date(2024, 12, 2), n_steps=96,
                                        freq_min=15, min_samples=4)
    assert len(point) == 96
    np.testing.assert_allclose(point, 0.5, atol=1e-9)


from planner.forecaster import SeasonalForecaster, build_forecaster


def _diurnal_his(col, n_days=3):
    times = pd.date_range("2024-11-04 00:00", periods=n_days * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    return pd.DataFrame({"_time": times.astype(str), col: np.where(day, 1800.0, 450.0)})


def test_seasonal_forecaster_produces_point_and_bands():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = _diurnal_his(col)
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0},
                                    "Data Hall 1F 2A ite-2": {"totalWatts": 1_800_000.0}}}
    his_col_for_room = {"Data Hall 1F 2A": col}
    fc = SeasonalForecaster(his, room2ite, his_col_for_room)
    forecast = fc.forecast(week_start=date(2024, 12, 2), n_steps=96)
    assert forecast.method == "seasonal"
    p50 = forecast.workload_schedules["Data Hall 1F 2A ite-1"]
    assert forecast.workload_schedules["Data Hall 1F 2A ite-2"] == p50      # room broadcast
    assert len(p50) == 96 and p50[40] > p50[4]                              # daytime > night
    assert forecast.bands["Data Hall 1F 2A ite-1"]["p50"] == p50            # workload IS p50
    assert "p10" in forecast.bands["Data Hall 1F 2A ite-1"]


def test_seasonal_load_is_week_start_aligned_unlike_persistence():
    # The fix for "IT load doesn't shift with week_start": seasonal climatology is keyed
    # by (weekday x time-of-day), so a week starting on a different weekday gets a
    # different per-step sequence; persistence (last-n_steps) ignores week_start.
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    times = pd.date_range("2024-11-04 00:00", periods=28 * 96, freq="15min", tz="Asia/Singapore")
    weekend = times.weekday >= 5
    df = pd.DataFrame({"_time": times.astype(str), col: np.where(weekend, 400.0, 1800.0)})
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    ite = "Data Hall 1F 2A ite-1"
    n = 7 * 96

    sea = SeasonalForecaster(df, room2ite, hcr)
    mon = sea.forecast(date(2024, 12, 2), n).workload_schedules[ite]   # Monday
    thu = sea.forecast(date(2024, 12, 5), n).workload_schedules[ite]   # Thursday
    assert mon != thu                                                  # seasonal IS week-aligned

    per = StatisticalForecaster(df, room2ite, hcr, method="persistence")
    assert (per.forecast(date(2024, 12, 2), n).workload_schedules[ite]
            == per.forecast(date(2024, 12, 5), n).workload_schedules[ite])  # persistence ignores week_start


def test_build_forecaster_selects_class_by_method():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = _diurnal_his(col)
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    assert isinstance(build_forecaster("seasonal", his, room2ite, hcr), SeasonalForecaster)
    assert isinstance(build_forecaster("persistence", his, room2ite, hcr), StatisticalForecaster)
    assert isinstance(build_forecaster("seasonal-naive", his, room2ite, hcr), StatisticalForecaster)


def test_forecast_carries_weather_file():
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]},
                  method="seasonal", weather_file="data/weather/real.epw")
    assert fc.weather_file == "data/weather/real.epw"


def test_forecasters_thread_weather_file_into_forecast():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    df = pd.DataFrame({col: [900.0] * 8})
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    fc = StatisticalForecaster(df, room2ite, hcr, method="persistence",
                               weather_file="data/weather/real.epw")
    out = fc.forecast(week_start=date(2024, 11, 11), n_steps=4)
    assert out.weather_file == "data/weather/real.epw"


def test_build_forecaster_threads_weather_file():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = _diurnal_his(col)
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    s = build_forecaster("seasonal", his, room2ite, hcr, weather_file="w.epw")
    assert s.forecast(date(2024, 12, 2), 96).weather_file == "w.epw"


# --- G1: calendar-aware load LEVEL (different calendar weeks track their period's level) ---

_LOAD_COL = "1F_Datahall 2A 1F Data Hall 2A IT loads"


def _two_month_his(low=1000.0, high=1400.0):
    """Nov 2024 at `low`, Dec 2024 at `high`, with an 08:00-20:00 day/night diurnal shape.
    cap=2_000_000 W so loading stays in (0,1). Used to test calendar-level tracking."""
    times = pd.date_range("2024-11-01 00:00", "2024-12-31 23:45", freq="15min",
                          tz="Asia/Singapore")
    base = np.where(times.month == 11, low, high)
    day = (times.hour >= 8) & (times.hour < 20)
    load = base * np.where(day, 1.0, 0.5)
    return pd.DataFrame({"_time": times.astype(str), _LOAD_COL: load})


def test_calendar_level_scale_tracks_period():
    his = _two_month_his()
    loading = loading_from_it_loads(his[_LOAD_COL], total_watts=2_000_000.0)
    s_nov = calendar_level_scale(loading, his["_time"], date(2024, 11, 15))
    s_dec = calendar_level_scale(loading, his["_time"], date(2024, 12, 15))
    assert s_nov < 1.0 < s_dec        # Nov below all-time mean, Dec above
    assert s_dec > s_nov


def test_calendar_level_scale_clamps_out_of_range_week():
    his = _two_month_his()
    loading = loading_from_it_loads(his[_LOAD_COL], total_watts=2_000_000.0)
    s_future = calendar_level_scale(loading, his["_time"], date(2025, 6, 1))
    s_dec = calendar_level_scale(loading, his["_time"], date(2024, 12, 15))
    assert 0.5 <= s_future <= 1.5
    np.testing.assert_allclose(s_future, s_dec, atol=0.05)   # clamps to the last (Dec) level


def test_calendar_level_scale_flat_history_is_unity():
    times = pd.date_range("2024-11-01 00:00", periods=4 * 96, freq="15min", tz="Asia/Singapore")
    loading = pd.Series(np.full(len(times), 0.5))
    assert calendar_level_scale(loading, pd.Series(times.astype(str)),
                                date(2024, 11, 2)) == 1.0


def test_seasonal_forecast_tracks_calendar_month():
    his = _two_month_his()
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 2_000_000.0}}}
    hcr = {"Data Hall 1F 2A": _LOAD_COL}
    ite = "Data Hall 1F 2A ite-1"
    fc = SeasonalForecaster(his, room2ite, hcr)
    nov = np.array(fc.forecast(date(2024, 11, 18), 96).workload_schedules[ite])   # Monday
    dec = np.array(fc.forecast(date(2024, 12, 16), 96).workload_schedules[ite])   # Monday
    assert nov.mean() < dec.mean()             # tracks the calendar period's level
    assert not np.allclose(nov, dec)           # different calendar weeks no longer identical


def test_seasonal_forecast_preserves_diurnal_shape_when_leveling():
    his = _two_month_his()
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 2_000_000.0}}}
    hcr = {"Data Hall 1F 2A": _LOAD_COL}
    ite = "Data Hall 1F 2A ite-1"
    fc = SeasonalForecaster(his, room2ite, hcr)
    nov = np.array(fc.forecast(date(2024, 11, 18), 96).workload_schedules[ite])
    dec = np.array(fc.forecast(date(2024, 12, 16), 96).workload_schedules[ite])
    # only the LEVEL shifts; the normalized diurnal shape is identical
    np.testing.assert_allclose(nov / nov.mean(), dec / dec.mean(), atol=1e-6)
