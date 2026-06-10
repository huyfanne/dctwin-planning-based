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


_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def weather_coverage(weather_file: str) -> dict:
    """Human + machine view of the EPW's covered window (month/day, year-agnostic)."""
    (sm, sd), (em, ed) = epw_data_period(weather_file)
    return {
        "label": f"{_MONTHS[sm]} {sd} – {_MONTHS[em]} {ed}",
        "start_md": f"{sm:02d}-{sd:02d}",
        "end_md": f"{em:02d}-{ed:02d}",
    }


def epw_first_date(weather_file: str) -> date:
    """First concrete date in the EPW data block (8 header lines, then CSV rows
    'year,month,day,hour,…'). Used to suggest an in-range default week_start."""
    rows = Path(weather_file).read_text().splitlines()
    f = rows[8].split(",")
    return date(int(f[0]), int(f[1]), int(f[2]))


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


def weather_timeseries(weather_file: str, start_date: date, days: int = 7) -> list[dict]:
    """Per-hour outdoor dry-bulb temperature for [start_date, start_date+days) from the
    EPW data rows. Returns [{"t": "YYYY-MM-DDTHH:00", "temp_c": float}]; [] if no rows
    fall in the window (e.g. the requested window is outside the EPW's coverage).

    EPW data block: 8 header lines, then CSV rows
    'year,month,day,hour,minute,datasource,dry_bulb,dew_point,rel_hum,…'. The hour field
    is 1-24; we map hour h -> (h-1):00 local so a day spans 00:00..23:00."""
    rows = Path(weather_file).read_text().splitlines()[8:]
    end = start_date + timedelta(days=days)
    out: list[dict] = []
    for line in rows:
        f = line.split(",")
        if len(f) < 7:
            continue
        try:
            rd = date(int(f[0]), int(f[1]), int(f[2]))
            hour = int(f[3])
            temp = float(f[6])
        except (ValueError, IndexError):
            continue
        if not (start_date <= rd < end):
            continue
        hh = min(23, max(0, hour - 1))
        out.append({"t": f"{rd.isoformat()}T{hh:02d}:00", "temp_c": temp})
    return out
