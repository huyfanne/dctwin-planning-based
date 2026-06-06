import numpy as np
import pandas as pd
from datetime import date

from planner.backtest_forecaster import mape, rmse, picp, backtest_room


def test_metrics_basic():
    actual = np.array([1.0, 2.0, 4.0])
    pred = np.array([1.0, 2.0, 2.0])
    assert rmse(actual, pred) > 0
    assert abs(mape(actual, pred) - (100.0 * (0 + 0 + 0.5) / 3)) < 1e-6
    lo = np.array([0.5, 1.5, 3.0]); hi = np.array([1.5, 2.5, 5.0])
    assert picp(actual, lo, hi) == 1.0
    assert picp(np.array([1.0, 9.0]), np.array([0.0, 0.0]), np.array([2.0, 2.0])) == 0.5


def test_backtest_room_seasonal_beats_persistence_on_diurnal():
    times = pd.date_range("2024-11-04 00:00", periods=4 * 7 * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = pd.DataFrame({"_time": times.astype(str), col: np.where(day, 1800.0, 450.0)})
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    res = backtest_room(his, room2ite, hcr, room="Data Hall 1F 2A", holdout_days=7)
    assert res["rmse_seasonal"] <= res["rmse_persistence"]
    assert 0.0 <= res["picp"] <= 1.0
