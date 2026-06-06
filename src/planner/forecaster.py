from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
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


@dataclass
class Forecast:
    week_start: date
    workload_schedules: dict[str, list[float]]   # ite name -> per-step loading
    method: str = "persistence"
    bands: Optional[dict] = None    # ITE -> {"p10","p50","p90"} per-step (seasonal only)

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
                 his_col_for_room: dict, method: str = "persistence"):
        self.his = his_data
        self.room2ite = room2ite
        self.his_col_for_room = his_col_for_room
        self.method = method

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
        return Forecast(week_start=week_start, workload_schedules=schedules, method=self.method)
