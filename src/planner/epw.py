"""Lightweight EPW coverage check — read the DATA PERIODS line to know which
(month, day) range the weather file covers, so we never request a week outside it."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


def epw_data_period(weather_file: str) -> tuple:
    """Return ((start_month, start_day), (end_month, end_day)) from the EPW's
    'DATA PERIODS' header line. Fields look like ' 11/ 1' and ' 1/31'."""
    for line in Path(weather_file).read_text().splitlines():
        if line.upper().startswith("DATA PERIODS"):
            parts = [p.strip() for p in line.split(",")]
            sm, sd = (int(x) for x in parts[-2].split("/"))
            em, ed = (int(x) for x in parts[-1].split("/"))
            return (sm, sd), (em, ed)
    raise ValueError(f"no DATA PERIODS line in EPW {weather_file}")


def _md_in_range(md: tuple, start: tuple, end: tuple) -> bool:
    """Is (month, day) within [start, end], allowing a year wrap (start > end)?"""
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


def week_within_epw(weather_file: str, week_start: date, days: int = 7) -> bool:
    """True if every day of the week falls within the EPW's data period."""
    start, end = epw_data_period(weather_file)
    for i in range(days):
        d = week_start + timedelta(days=i)
        if not _md_in_range((d.month, d.day), start, end):
            return False
    return True
