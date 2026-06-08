from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from planner.types import SearchSpace, Setpoints

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BaselineColumns:
    """Regex patterns selecting the as-operated control columns in the history CSV.

    Patterns are matched with re.search against column names, so they can be partial
    (anchored with `$` to avoid catching e.g. *ReturnTemperature). Multiple matching
    columns (one per CRAH/chiller) are pooled and the median is taken.
    """

    sat_supply_temp: str   # CRAH/CRAC supply-air temperature columns
    chwst_supply_temp: str  # chiller chilled-water supply-temperature columns
    fan_speed: str          # CRAH/CRAC fan-speed (0-1 fraction) columns


def _match(df, pattern: str) -> list[str]:
    return [c for c in df.columns if re.search(pattern, c)]


def _pooled_median(df, cols: list[str]):
    if not cols:
        return None
    vals = df[cols].to_numpy(dtype=float).ravel()
    if vals.size == 0 or np.all(np.isnan(vals)):
        return None
    return float(np.nanmedian(vals))


def as_operated_setpoints(his_data, space: SearchSpace, cols: BaselineColumns,
                          design_flow_kg_s_per_acu: float,
                          fan_speed_max: float = 1.0) -> Setpoints:
    """Derive the plant's current ("as-operated") setpoints from telemetry medians.

    SAT  = median CRAH supply-air temperature.
    CHWST = median chiller chilled-water supply temperature.
    flow = (median CRAH fan-speed / fan_speed_max) * design mass-flow per ACU.
        `fan_speed_max` is the fan-speed value at full speed: 1.0 if the column is a
        0-1 fraction, 100.0 if it is a percentage.
    Each is clipped to the search-space bounds. Any signal absent from the data
    falls back to that axis' mid-range (logged), so a missing column never crashes a plan.
    """
    sat = _pooled_median(his_data, _match(his_data, cols.sat_supply_temp))
    chwst = _pooled_median(his_data, _match(his_data, cols.chwst_supply_temp))
    fan = _pooled_median(his_data, _match(his_data, cols.fan_speed))

    def _mid(b):
        return (b.lb + b.ub) / 2

    sat_c = space.sat.clip(sat) if sat is not None else _mid(space.sat)
    chwst_c = space.chwst.clip(chwst) if chwst is not None else _mid(space.chwst)
    if fan is not None:
        flow_kg_s = space.flow.clip((fan / fan_speed_max) * design_flow_kg_s_per_acu)
    else:
        logger.warning("as_operated_setpoints: no fan-speed column; using mid-range flow")
        flow_kg_s = _mid(space.flow)
    return Setpoints(sat_c, flow_kg_s, chwst_c)
