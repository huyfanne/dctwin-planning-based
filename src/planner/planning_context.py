"""Pure helpers that assemble the New-Plan planning-context time series:
past + forecast IT load (kW) for the controlled hall. Weather series live in epw.py.
No EnergyPlus, no I/O beyond the DataFrame/Forecast passed in — easy to unit-test."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


def past_hall_load_kw(his: pd.DataFrame, time_col: str, load_col: str,
                      start_date: date, days: int = 7) -> list[dict]:
    """[{"t","kw"}] of the hall IT load (kW) over [start_date, start_date+days).

    The history column is already kW. Timestamps are treated as local wall-clock
    (the data is Singapore-local); returns [] if the column/time is missing or no rows
    fall in the window (e.g. the window precedes the history coverage)."""
    if load_col not in his.columns or time_col not in his.columns:
        return []
    t = pd.to_datetime(his[time_col], errors="coerce")
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_localize(None)        # compare on local wall-clock
    start = pd.Timestamp(start_date)
    end = start + pd.Timedelta(days=days)
    mask = (t >= start) & (t < end)
    out: list[dict] = []
    for ts, kw in zip(t[mask], his.loc[mask, load_col]):
        if pd.isna(ts) or pd.isna(kw):
            continue
        out.append({"t": ts.strftime("%Y-%m-%dT%H:%M"), "kw": round(float(kw), 1)})
    return out


def forecast_hall_load_kw(forecast: Any, ite_caps_kw: dict[str, float],
                          week_start: date, timesteps_per_hour: int = 4) -> list[dict]:
    """[{"t","kw"}] aggregate hall IT-load forecast (kW) = Σ_ite fraction[ite][i]·cap_kw[ite].

    `forecast.workload_schedules` maps ITE name -> per-step loading fraction (0-1).
    `ite_caps_kw` maps ITE name -> capacity (kW). Only ITEs present in both are summed;
    returns [] if none overlap."""
    ws = getattr(forecast, "workload_schedules", None) or {}
    ites = [k for k in ite_caps_kw if k in ws and ws[k]]
    if not ites:
        return []
    n = min(len(ws[k]) for k in ites)
    step_min = 60 // max(1, timesteps_per_hour)
    base = datetime(week_start.year, week_start.month, week_start.day)
    out: list[dict] = []
    for i in range(n):
        kw = sum(float(ws[k][i]) * float(ite_caps_kw[k]) for k in ites)
        ts = base + timedelta(minutes=i * step_min)
        out.append({"t": ts.strftime("%Y-%m-%dT%H:%M"), "kw": round(kw, 1)})
    return out
