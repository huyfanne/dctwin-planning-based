from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class WeekPeriod:
    begin_month: int
    begin_day: int
    end_month: int
    end_day: int


def compute_week_period(week_start: date, days: int = 7) -> WeekPeriod:
    """Inclusive run period for a `days`-long week starting at week_start.

    EnergyPlus RunPeriod end day is inclusive, so a 7-day week ends at
    week_start + (days - 1). v1 rejects windows that cross a year boundary
    (dctwin hardcodes year 2013 and mishandles wrap).
    """
    end = week_start + timedelta(days=days - 1)
    if end.year != week_start.year:
        raise ValueError(
            f"week {week_start}..{end} crosses a year boundary; not supported in v1"
        )
    return WeekPeriod(week_start.month, week_start.day, end.month, end.day)


def write_week_config(
    base_prototxt: Union[str, Path],
    week_start: date,
    out_path: Union[str, Path],
    days: int = 7,
    timesteps_per_hour: int | None = None,
) -> str:
    """Read the base DT prototxt, set the weekly run period, write to out_path.

    Imports dctwin lazily so the pure logic above stays import-free for unit tests.
    """
    from dctwin.utils import read_engine_config
    from google.protobuf import text_format

    period = compute_week_period(week_start, days)
    cfg = read_engine_config(str(base_prototxt))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    stc = env_cfg.simulation_time_config
    stc.begin_month = period.begin_month
    stc.begin_day_of_month = period.begin_day
    stc.end_month = period.end_month
    stc.end_day_of_month = period.end_day
    if timesteps_per_hour is not None:
        stc.number_of_timesteps_per_hour = timesteps_per_hour
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(text_format.MessageToString(cfg))
    return str(out_path)
