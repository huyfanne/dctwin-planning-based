from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def loading_from_it_loads(it_loads_kw: pd.Series, total_watts: float) -> pd.Series:
    """Convert per-hall IT load (kW) to a 0-1 CPU-loading fraction."""
    capacity_kw = total_watts / 1000.0
    return (it_loads_kw / capacity_kw).clip(lower=0.0, upper=1.0)


def persistence_window(series: pd.Series, n_steps: int) -> np.ndarray:
    """Last n_steps of the series; tile if history is shorter than n_steps."""
    arr = series.to_numpy(dtype=float)
    if len(arr) >= n_steps:
        return arr[-n_steps:]
    reps = int(np.ceil(n_steps / max(len(arr), 1)))
    return np.tile(arr, reps)[:n_steps]


def seasonal_climatology(loading, times, week_start, n_steps: int,
                         freq_min: int = 15, min_samples: int = 4):
    """(weekday, time-of-day) climatology of `loading` indexed by `times`.

    Returns (point, bands): point = per-step p50 (median) array of length n_steps for
    the forecast week starting at `week_start` 00:00; bands = {"p10","p50","p90"} arrays.
    Buckets with < min_samples observations fall back to the hour-of-day pooled
    climatology, then to the global percentiles. Local (SGT) calendar components are used.
    """
    v = np.asarray(loading, dtype=float)
    t = pd.to_datetime(pd.Series(times).to_numpy(), utc=True).tz_convert("Asia/Singapore")
    df = pd.DataFrame({
        "v": v,
        "wd": t.weekday.to_numpy(),
        "tb": ((t.hour * 60 + t.minute) // freq_min).to_numpy(),
        "hr": t.hour.to_numpy(),
    })
    pcts = {"p10": 10.0, "p50": 50.0, "p90": 90.0}

    def _agg(group_cols):
        g = df.groupby(group_cols)["v"]
        out = {k: g.apply(lambda s, q=q: float(np.percentile(s, q))) for k, q in pcts.items()}
        out["n"] = g.size()
        return pd.DataFrame(out)

    by_wd_tb = _agg(["wd", "tb"])
    by_hr = _agg(["hr"])
    g_all = {k: float(np.percentile(v, q)) for k, q in pcts.items()}

    out = {"p10": [], "p50": [], "p90": []}
    base = datetime(week_start.year, week_start.month, week_start.day)
    for i in range(n_steps):
        ts = base + timedelta(minutes=freq_min * i)
        key = (ts.weekday(), (ts.hour * 60 + ts.minute) // freq_min)
        if key in by_wd_tb.index and by_wd_tb.loc[key, "n"] >= min_samples:
            row = by_wd_tb.loc[key]
        elif ts.hour in by_hr.index:
            row = by_hr.loc[ts.hour]
        else:
            row = g_all
        for k in out:
            out[k].append(float(row[k]))
    point = np.array(out["p50"])
    bands = {k: np.array(out[k]) for k in out}
    return point, bands


@dataclass
class Forecast:
    week_start: date
    workload_schedules: dict[str, list[float]]   # ite name -> per-step loading
    method: str = "persistence"
    bands: Optional[dict] = None    # ITE -> {"p10","p50","p90"} per-step (seasonal only)
    weather_file: Optional[str] = None   # per-forecast EPW path (FB)

    def materialize(self, project_root: str) -> None:
        """Write each ITE's workload array to data/schedule/workloads/<name>.json.

        File name convention matches the GDS layout: lowercased ITE name.
        """
        out_dir = Path(project_root) / "data" / "schedule" / "workloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        for ite_name, arr in self.workload_schedules.items():
            fname = ite_name.lower() + ".json"
            (out_dir / fname).write_text(json.dumps(list(arr)))


class StatisticalForecaster:
    """Persistence / seasonal-naive forecaster over per-hall IT loads."""

    def __init__(self, his_data: pd.DataFrame, room2ite: dict,
                 his_col_for_room: dict, method: str = "persistence",
                 weather_file: Optional[str] = None):
        self.his = his_data
        self.room2ite = room2ite
        self.his_col_for_room = his_col_for_room
        self.method = method
        self.weather_file = weather_file

    def _hall_loading(self, room: str, n_steps: int) -> np.ndarray:
        col = self.his_col_for_room[room]
        ites = self.room2ite[room]
        total_watts = sum(v["totalWatts"] for v in ites.values())
        loading = loading_from_it_loads(self.his[col], total_watts)
        if self.method in ("persistence", "seasonal-naive"):
            return persistence_window(loading, n_steps)
        raise ValueError(f"unknown method {self.method!r}")

    def forecast(self, week_start: date, n_steps: int) -> Forecast:
        schedules: dict[str, list[float]] = {}
        for room, ites in self.room2ite.items():
            if room not in self.his_col_for_room:
                continue
            hall = self._hall_loading(room, n_steps)
            for ite_name in ites:
                schedules[ite_name] = [float(x) for x in hall]
        return Forecast(week_start=week_start, workload_schedules=schedules, method=self.method,
                        weather_file=self.weather_file)


class SeasonalForecaster:
    """Day-of-week x time-of-day climatology forecaster with p10/p50/p90 bands."""

    def __init__(self, his_data: pd.DataFrame, room2ite: dict, his_col_for_room: dict,
                 time_col: str = "_time", freq_min: int = 15, min_samples: int = 4,
                 weather_file: Optional[str] = None):
        self.his = his_data
        self.room2ite = room2ite
        self.his_col_for_room = his_col_for_room
        self.time_col = time_col
        self.freq_min = freq_min
        self.min_samples = min_samples
        self.weather_file = weather_file

    def forecast(self, week_start: date, n_steps: int) -> Forecast:
        times = self.his[self.time_col]
        schedules: dict[str, list[float]] = {}
        bands: dict[str, dict] = {}
        for room, ites in self.room2ite.items():
            if room not in self.his_col_for_room:
                continue
            total_watts = sum(v["totalWatts"] for v in ites.values())
            loading = loading_from_it_loads(self.his[self.his_col_for_room[room]], total_watts)
            point, band = seasonal_climatology(loading, times, week_start, n_steps,
                                               freq_min=self.freq_min, min_samples=self.min_samples)
            p50 = [float(x) for x in point]
            room_band = {k: [float(x) for x in band[k]] for k in band}
            for ite_name in ites:
                schedules[ite_name] = p50
                bands[ite_name] = room_band
        return Forecast(week_start=week_start, workload_schedules=schedules,
                        method="seasonal", bands=bands, weather_file=self.weather_file)


def build_forecaster(method: str, his_data, room2ite: dict, his_col_for_room: dict,
                     time_col: str = "_time", weather_file=None):
    """Construct the forecaster for `method`: 'seasonal' -> SeasonalForecaster,
    anything else ('persistence'/'seasonal-naive') -> StatisticalForecaster."""
    if method == "seasonal":
        return SeasonalForecaster(his_data, room2ite, his_col_for_room,
                                  time_col=time_col, weather_file=weather_file)
    return StatisticalForecaster(his_data, room2ite, his_col_for_room,
                                 method=method, weather_file=weather_file)
