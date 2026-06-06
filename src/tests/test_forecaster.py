import json
from datetime import date

import numpy as np
import pandas as pd

from planner.forecaster import (
    loading_from_it_loads, persistence_window, StatisticalForecaster, Forecast,
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
