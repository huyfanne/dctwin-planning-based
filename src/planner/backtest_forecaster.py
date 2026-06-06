"""Backtest the seasonal forecaster vs persistence on held-out real telemetry.
Reports per-room MAPE/RMSE and band calibration (PICP). Substantiates 'realism'."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from planner.forecaster import (
    SeasonalForecaster, StatisticalForecaster, loading_from_it_loads,
)

STEPS_PER_DAY = 96   # 15-min cadence


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def mape(actual: np.ndarray, pred: np.ndarray, eps: float = 1e-9) -> float:
    return float(100.0 * np.mean(np.abs((actual - pred) / np.maximum(np.abs(actual), eps))))


def picp(actual: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Prediction-interval coverage probability: fraction of actuals within [lo, hi]."""
    return float(np.mean((actual >= lo) & (actual <= hi)))


def backtest_room(his: pd.DataFrame, room2ite: dict, his_col_for_room: dict,
                  room: str, holdout_days: int = 14, time_col: str = "_time") -> dict:
    """Fit on all-but-last holdout_days, forecast the holdout, compare seasonal vs
    persistence for one room. Returns a metrics dict."""
    n_hold = holdout_days * STEPS_PER_DAY
    train, test = his.iloc[:-n_hold], his.iloc[-n_hold:]
    col = his_col_for_room[room]
    total_watts = sum(v["totalWatts"] for v in room2ite[room].values())
    actual = loading_from_it_loads(test[col], total_watts).to_numpy(dtype=float)

    ws = pd.to_datetime(test[time_col].to_numpy(), utc=True).tz_convert("Asia/Singapore")
    week_start = ws[0].date()

    seasonal = SeasonalForecaster(train, room2ite, his_col_for_room, time_col=time_col)
    sf = seasonal.forecast(week_start, n_hold)
    ite0 = next(iter(room2ite[room]))
    p50 = np.array(sf.workload_schedules[ite0])
    lo = np.array(sf.bands[ite0]["p10"]); hi = np.array(sf.bands[ite0]["p90"])

    persist = StatisticalForecaster(train, room2ite, his_col_for_room, method="persistence")
    pf = persist.forecast(week_start, n_hold)
    pp = np.array(pf.workload_schedules[ite0])

    return {
        "room": room, "holdout_days": holdout_days,
        "rmse_seasonal": rmse(actual, p50), "rmse_persistence": rmse(actual, pp),
        "mape_seasonal": mape(actual, p50), "mape_persistence": mape(actual, pp),
        "picp": picp(actual, lo, hi),
    }


def main(his_csv: str = "data/his_data_processed.csv",
         room2ite_path: str = "configs/dt/room2ite_map.json",
         forecaster_pkl: str = "models/forecaster.pkl",
         holdout_days: int = 14) -> list[dict]:
    import pickle
    his = pd.read_csv(his_csv)
    room2ite = json.loads(Path(room2ite_path).read_text())
    cfg = pickle.loads(Path(forecaster_pkl).read_bytes())
    hcr = cfg["his_col_for_room"]
    rows = []
    for room in hcr:
        try:
            rows.append(backtest_room(his, room2ite, hcr, room, holdout_days))
        except Exception as e:
            rows.append({"room": room, "error": str(e)})
    for r in rows:
        print(r)
    return rows


if __name__ == "__main__":
    main()
