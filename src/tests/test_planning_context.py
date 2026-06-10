"""Tests for the New-Plan planning-context helpers: EPW weather series + IT-load series."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from planner.epw import weather_timeseries
from planner.planning_context import past_hall_load_kw, forecast_hall_load_kw


# ---- a tiny valid EPW (8 header lines, then 'year,month,day,hour,minute,src,drybulb,...') ----
def _write_epw(tmp_path: Path) -> str:
    header = ["LOCATION,Test,,,,,,,0,0,0,0"] + [f"H{i}" for i in range(6)] + [
        "DATA PERIODS,1,1,Data,Sunday, 11/ 1, 11/ 5"]
    rows = []
    for d in (1, 2, 3, 4):              # Nov 1-4, 2024, 24 hourly rows each
        for h in range(1, 25):
            temp = 28.0 + h * 0.1 + d   # deterministic, distinguishable
            rows.append(f"2024,11,{d},{h},0,C9,{temp:.1f},20.0,80,101325,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
    (tmp_path / "t.epw").write_text("\n".join(header + rows))
    return str(tmp_path / "t.epw")


def test_weather_timeseries_in_window(tmp_path):
    epw = _write_epw(tmp_path)
    ts = weather_timeseries(epw, date(2024, 11, 2), days=2)   # Nov 2-3
    assert len(ts) == 48                                      # 2 days x 24 h
    assert ts[0]["t"] == "2024-11-02T00:00"                   # hour 1 -> 00:00
    assert ts[-1]["t"] == "2024-11-03T23:00"
    assert ts[0]["temp_c"] == 28.0 + 0.1 + 2                  # h=1, d=2


def test_weather_timeseries_out_of_coverage(tmp_path):
    epw = _write_epw(tmp_path)
    assert weather_timeseries(epw, date(2024, 12, 1), days=7) == []   # beyond the data rows


def test_past_hall_load_kw_slices_window():
    times = pd.date_range("2024-11-05 00:00", periods=8 * 96, freq="15min", tz="Asia/Singapore")
    his = pd.DataFrame({"_time": times.astype(str), "load": [900.0 + i % 10 for i in range(len(times))]})
    out = past_hall_load_kw(his, "_time", "load", date(2024, 11, 6), days=2)
    assert len(out) == 2 * 96                       # exactly 2 days at 15-min
    assert out[0]["t"] == "2024-11-06T00:00"
    assert out[0]["kw"] == 900.0 + (96 % 10)        # first row of Nov 6


def test_past_hall_load_kw_missing_column():
    his = pd.DataFrame({"_time": ["2024-11-06 00:00:00+08:00"], "other": [1.0]})
    assert past_hall_load_kw(his, "_time", "load", date(2024, 11, 6), days=1) == []


def test_past_hall_load_kw_window_before_data():
    his = pd.DataFrame({"_time": ["2024-11-06 00:00:00+08:00"], "load": [900.0]})
    assert past_hall_load_kw(his, "_time", "load", date(2024, 10, 1), days=7) == []


@dataclass
class _FakeForecast:
    workload_schedules: dict


def test_forecast_hall_load_kw_aggregates_capacity():
    fc = _FakeForecast({"ite-1": [0.5, 0.6], "ite-2": [0.5, 0.6]})
    caps = {"ite-1": 1000.0, "ite-2": 1000.0}       # 2000 kW total
    out = forecast_hall_load_kw(fc, caps, date(2024, 11, 8), timesteps_per_hour=4)
    assert [r["kw"] for r in out] == [1000.0, 1200.0]   # 0.5*2000, 0.6*2000
    assert out[0]["t"] == "2024-11-08T00:00"
    assert out[1]["t"] == "2024-11-08T00:15"            # 15-min step


def test_forecast_hall_load_kw_no_overlap():
    fc = _FakeForecast({"ite-9": [0.5]})
    assert forecast_hall_load_kw(fc, {"ite-1": 1000.0}, date(2024, 11, 8)) == []
