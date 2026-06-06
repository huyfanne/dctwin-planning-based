# Forecast Realism FA — Seasonal Forecaster + Uncertainty + Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the naive persistence IT-load forecast with a real day-of-week × time-of-day seasonal climatology that emits p10/p50/p90 uncertainty bands, and add a backtest that proves it beats persistence on held-out real telemetry.

**Architecture:** A pure `seasonal_climatology` function bins the real 15-min history by `(weekday, time-of-day)` and returns a per-step p50 point series + p10/p50/p90 bands (thin buckets fall back to hour-of-day, then global). A `SeasonalForecaster` wraps it per room (broadcasting to ITEs) and returns the existing `Forecast` object, now carrying `bands`. A `build_forecaster` factory selects persistence vs seasonal by `method`, wired into `run_plan_job`/`run_deploy_job`. A `backtest_forecaster` harness holds out the last N days and reports MAPE/RMSE vs persistence + band calibration (PICP). This is phase FA of `docs/superpowers/specs/2026-06-06-forecast-realism-design.md`; FB (real-weather seam) and FC (uncertainty surfacing + P2b joint scenarios) follow.

**Tech Stack:** Python 3.13, pandas, numpy, pytest. Backend tests from `src/`: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest`.

---

## Grounding facts (verified against current code)

- **`Forecast`** (`planner/forecaster.py:28-43`, `@dataclass`): fields `week_start: date`, `workload_schedules: dict[str, list[float]]` (ITE→per-step), `method: str = "persistence"`; `materialize(project_root)` writes each ITE's p50 series to `data/schedule/workloads/<ite_lower>.json`.
- **`StatisticalForecaster`** (`forecaster.py:46-73`): `__init__(his_data, room2ite, his_col_for_room, method="persistence")`; `_hall_loading(room, n_steps)` → `loading_from_it_loads(his[col], total_watts)` then `persistence_window`; `forecast(week_start, n_steps)` broadcasts the room loading to every ITE. `method in ("persistence","seasonal-naive")` both run persistence (the latter is a misnomer).
- **`loading_from_it_loads(it_loads_kw, total_watts)`** (`forecaster.py:13-16`): `(it_loads_kw / (total_watts/1000)).clip(0,1)`.
- **History CSV** (`data/his_data_processed.csv`): first column **`_time`** = tz-aware ISO timestamps (`2024-11-05 08:00:00+08:00`), **15-min** cadence; loaded in `jobs.py` via `pd.read_csv(fc_cfg["his_csv"])` (NO `parse_dates`, so `_time` is a string column). Per-room IT-load columns end with `"IT loads"`.
- **Production construction** (`webapp/jobs.py`): `run_plan_job` line ~103 and `run_deploy_job` line ~183 both do `StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"], method=fc_cfg["method"])`. `his = pd.read_csv(fc_cfg["his_csv"])`.
- **`fit_forecaster.main(his_csv, room2ite_path, method, out_path)`** (`fit_forecaster.py:42-56`) pickles `{method, his_csv, room2ite_path, his_col_for_room}`; already takes a `method` arg (so `method="seasonal"` flows through unchanged).
- **Tests** live in `src/tests/test_forecaster.py` (existing persistence tests show fixture style: a small DataFrame + `room2ite` + `his_col_for_room`).

## File Structure

- **Modify** `src/planner/forecaster.py` — add `Forecast.bands`; add pure `seasonal_climatology`; add `SeasonalForecaster`; add `build_forecaster` factory.
- **Modify** `src/tests/test_forecaster.py` — bands field, seasonal climatology, SeasonalForecaster, factory tests.
- **Create** `src/planner/backtest_forecaster.py` — `mape`/`rmse`/`picp` metrics + `backtest_room` + `main`.
- **Create** `src/tests/test_backtest_forecaster.py`.
- **Modify** `src/webapp/jobs.py` — use `build_forecaster` in `run_plan_job` + `run_deploy_job`.

**Point-vs-band resolution:** the point forecast IS the p50 (median) band, so `workload_schedules == bands["p50"]` (robust to the occasional spike in flat data; reconciles the spec's "mean"/"p50" wording to median).

---

## Task 1: `Forecast.bands` field

**Files:** Modify `src/planner/forecaster.py`; Test `src/tests/test_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_forecaster.py
def test_forecast_carries_optional_bands():
    fc = Forecast(week_start=date(2024, 11, 11),
                  workload_schedules={"ite-1": [0.5, 0.5]},
                  method="seasonal",
                  bands={"ite-1": {"p10": [0.4, 0.4], "p50": [0.5, 0.5], "p90": [0.6, 0.6]}})
    assert fc.bands["ite-1"]["p90"] == [0.6, 0.6]


def test_forecast_bands_default_none():
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]})
    assert fc.bands is None        # back-compat: persistence forecasts have no bands
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py::test_forecast_carries_optional_bands -q`
Expected: FAIL (`__init__() got an unexpected keyword argument 'bands'`).

- [ ] **Step 3: Implement**

In `src/planner/forecaster.py`, add a field to the `Forecast` dataclass (after `method`):
```python
    method: str = "persistence"
    bands: Optional[dict] = None    # ITE -> {"p10","p50","p90"} per-step (seasonal only)
```
(`Optional` is already imported.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py -q`
Expected: PASS (new tests + all existing forecaster tests — the field defaults to None).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/forecaster.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): Forecast carries optional p10/p50/p90 bands"
```

---

## Task 2: `seasonal_climatology` pure function

**Files:** Modify `src/planner/forecaster.py`; Test `src/tests/test_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_forecaster.py
from planner.forecaster import seasonal_climatology


def test_seasonal_climatology_captures_diurnal_shape():
    # 3 weeks of 15-min data with a clean day/night step: 0.8 from 08:00-19:45, else 0.2
    times = pd.date_range("2024-11-04 00:00", periods=3 * 7 * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    loading = pd.Series(np.where(day, 0.8, 0.2), index=range(len(times)))
    # forecast a future Monday week, 1 day = 96 steps
    point, bands = seasonal_climatology(loading, pd.Series(times.astype(str)),
                                        week_start=date(2024, 12, 2), n_steps=96, freq_min=15)
    assert len(point) == 96 and set(bands) == {"p10", "p50", "p90"}
    # step 40 = 10:00 (daytime) high; step 4 = 01:00 (night) low
    assert point[40] > 0.7 and point[4] < 0.3
    # bands ordered p10 <= p50 <= p90 everywhere
    assert np.all(bands["p10"] <= bands["p50"]) and np.all(bands["p50"] <= bands["p90"])


def test_seasonal_climatology_thin_bucket_falls_back():
    # only 2 days of history -> most (weekday,tod) buckets have <4 samples -> hour-of-day fallback
    times = pd.date_range("2024-11-04 00:00", periods=2 * 96, freq="15min", tz="Asia/Singapore")
    loading = pd.Series(np.full(len(times), 0.5), index=range(len(times)))
    point, bands = seasonal_climatology(loading, pd.Series(times.astype(str)),
                                        week_start=date(2024, 12, 2), n_steps=96,
                                        freq_min=15, min_samples=4)
    assert len(point) == 96
    np.testing.assert_allclose(point, 0.5, atol=1e-9)   # fallback still yields the constant level
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py::test_seasonal_climatology_captures_diurnal_shape -q`
Expected: FAIL (`cannot import name 'seasonal_climatology'`).

- [ ] **Step 3: Implement**

In `src/planner/forecaster.py`, add (after `persistence_window`; add `from datetime import date, datetime, timedelta` — the module currently imports only `date`, so extend that import line):
```python
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
    wd = t.weekday.to_numpy()
    tb = ((t.hour * 60 + t.minute) // freq_min).to_numpy()
    hr = t.hour.to_numpy()

    df = pd.DataFrame({"v": v, "wd": wd, "tb": tb, "hr": hr})
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py -q`
Expected: PASS (both new tests + existing).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/forecaster.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): seasonal_climatology (weekday x time-of-day) + p10/p50/p90 bands + fallback"
```

---

## Task 3: `SeasonalForecaster` class

**Files:** Modify `src/planner/forecaster.py`; Test `src/tests/test_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_forecaster.py
from planner.forecaster import SeasonalForecaster


def _diurnal_his(col, n_days=3):
    times = pd.date_range("2024-11-04 00:00", periods=n_days * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    return pd.DataFrame({"_time": times.astype(str), col: np.where(day, 1800.0, 450.0)})


def test_seasonal_forecaster_produces_point_and_bands():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = _diurnal_his(col)
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0},
                                    "Data Hall 1F 2A ite-2": {"totalWatts": 1_800_000.0}}}
    his_col_for_room = {"Data Hall 1F 2A": col}
    fc = SeasonalForecaster(his, room2ite, his_col_for_room)            # time_col defaults to "_time"
    forecast = fc.forecast(week_start=date(2024, 12, 2), n_steps=96)
    assert forecast.method == "seasonal"
    # both ITEs in the room share the room climatology (broadcast)
    p50 = forecast.workload_schedules["Data Hall 1F 2A ite-1"]
    assert forecast.workload_schedules["Data Hall 1F 2A ite-2"] == p50
    assert len(p50) == 96 and p50[40] > p50[4]                          # daytime > night
    # workload_schedules IS the p50 band
    assert forecast.bands["Data Hall 1F 2A ite-1"]["p50"] == p50
    assert "p10" in forecast.bands["Data Hall 1F 2A ite-1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py::test_seasonal_forecaster_produces_point_and_bands -q`
Expected: FAIL (`cannot import name 'SeasonalForecaster'`).

- [ ] **Step 3: Implement**

In `src/planner/forecaster.py`, add after `StatisticalForecaster`:
```python
class SeasonalForecaster:
    """Day-of-week x time-of-day climatology forecaster with p10/p50/p90 bands."""

    def __init__(self, his_data: pd.DataFrame, room2ite: dict, his_col_for_room: dict,
                 time_col: str = "_time", freq_min: int = 15, min_samples: int = 4):
        self.his = his_data
        self.room2ite = room2ite
        self.his_col_for_room = his_col_for_room
        self.time_col = time_col
        self.freq_min = freq_min
        self.min_samples = min_samples

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
                        method="seasonal", bands=bands)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/forecaster.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): SeasonalForecaster (per-room climatology, p50 point + bands)"
```

---

## Task 4: `build_forecaster` factory + production wiring

**Files:** Modify `src/planner/forecaster.py`, `src/webapp/jobs.py`; Test `src/tests/test_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_forecaster.py
from planner.forecaster import build_forecaster


def test_build_forecaster_selects_class_by_method():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = _diurnal_his(col)
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    assert isinstance(build_forecaster("seasonal", his, room2ite, hcr), SeasonalForecaster)
    assert isinstance(build_forecaster("persistence", his, room2ite, hcr), StatisticalForecaster)
    assert isinstance(build_forecaster("seasonal-naive", his, room2ite, hcr), StatisticalForecaster)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py::test_build_forecaster_selects_class_by_method -q`
Expected: FAIL (`cannot import name 'build_forecaster'`).

- [ ] **Step 3: Implement**

In `src/planner/forecaster.py`, add at the end:
```python
def build_forecaster(method: str, his_data, room2ite: dict, his_col_for_room: dict,
                     time_col: str = "_time"):
    """Construct the forecaster for `method`: 'seasonal' -> SeasonalForecaster,
    anything else ('persistence'/'seasonal-naive') -> StatisticalForecaster."""
    if method == "seasonal":
        return SeasonalForecaster(his_data, room2ite, his_col_for_room, time_col=time_col)
    return StatisticalForecaster(his_data, room2ite, his_col_for_room, method=method)
```
In `src/webapp/jobs.py`: change the lazy import `from planner.forecaster import StatisticalForecaster` to `from planner.forecaster import build_forecaster` in BOTH `run_plan_job` and `run_deploy_job`, and replace each `StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"], method=fc_cfg["method"])` construction with:
```python
    forecaster = build_forecaster(fc_cfg["method"], his, room2ite, fc_cfg["his_col_for_room"])
```

- [ ] **Step 4: Run tests to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py tests/test_jobs.py -q && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "import webapp.jobs"`
Expected: PASS + clean import.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/forecaster.py src/webapp/jobs.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): build_forecaster factory + wire seasonal into plan/deploy jobs"
```

---

## Task 5: Backtest harness (MAPE / RMSE / PICP)

**Files:** Create `src/planner/backtest_forecaster.py`; Test `src/tests/test_backtest_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_backtest_forecaster.py
import numpy as np
import pandas as pd
from datetime import date

from planner.backtest_forecaster import mape, rmse, picp, backtest_room


def test_metrics_basic():
    actual = np.array([1.0, 2.0, 4.0])
    pred = np.array([1.0, 2.0, 2.0])
    assert rmse(actual, pred) > 0
    assert abs(mape(actual, pred) - (100.0 * (0 + 0 + 0.5) / 3)) < 1e-6
    # PICP: fraction of actuals within [lo, hi]
    lo = np.array([0.5, 1.5, 3.0]); hi = np.array([1.5, 2.5, 5.0])
    assert picp(actual, lo, hi) == 1.0
    assert picp(np.array([1.0, 9.0]), np.array([0.0, 0.0]), np.array([2.0, 2.0])) == 0.5


def test_backtest_room_seasonal_beats_persistence_on_diurnal():
    # 4 weeks of clean diurnal history; hold out the last 7 days
    times = pd.date_range("2024-11-04 00:00", periods=4 * 7 * 96, freq="15min", tz="Asia/Singapore")
    day = (times.hour >= 8) & (times.hour < 20)
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    his = pd.DataFrame({"_time": times.astype(str), col: np.where(day, 1800.0, 450.0)})
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    res = backtest_room(his, room2ite, hcr, room="Data Hall 1F 2A", holdout_days=7)
    # seasonal should track the diurnal cycle better than persistence (lower RMSE)
    assert res["rmse_seasonal"] <= res["rmse_persistence"]
    assert 0.0 <= res["picp"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_backtest_forecaster.py -q`
Expected: FAIL (`No module named 'planner.backtest_forecaster'`).

- [ ] **Step 3: Implement (create `src/planner/backtest_forecaster.py`)**

```python
"""Backtest the seasonal forecaster vs persistence on held-out real telemetry.
Reports per-room MAPE/RMSE and band calibration (PICP). Substantiates 'realism'."""
from __future__ import annotations

import json
from datetime import date, timedelta
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
    week_start = ws[0].date()        # numpy array -> DatetimeIndex (tz_convert works); ws[0] is a Timestamp

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
        except Exception as e:  # a room with too little/mismatched data shouldn't abort the report
            rows.append({"room": room, "error": str(e)})
    for r in rows:
        print(r)
    return rows


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_backtest_forecaster.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/backtest_forecaster.py src/tests/test_backtest_forecaster.py
git commit -m "feat(dtwin): forecaster backtest harness (MAPE/RMSE vs persistence + PICP)"
```

---

## Task 6: Full-suite verification + real-data backtest run

**Files:** none (verification).

- [ ] **Step 1: Full backend suite**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q 2>&1 | tail -2`
Expected: all pass (prior suite + the new forecaster/backtest tests), 5 deselected (integration).

- [ ] **Step 2: Run the backtest on the REAL telemetry (sanity, not a gate)**

First ensure a forecaster.pkl exists (build one if needed): `PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "import fit_forecaster; fit_forecaster.main(method='seasonal')"`
Then: `PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m planner.backtest_forecaster 2>&1 | tail -10`
Expected: prints a per-room metrics row for each mapped room with `rmse_seasonal`, `rmse_persistence`, `mape_*`, and `picp`. Record the result (the flat-load caveat means gains may be modest; PICP near ~0.8 indicates honest bands). This is a sanity run, not a CI gate.

- [ ] **Step 3: Commit (doc the backtest result, optional)**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add -A && git commit -m "test(dtwin): FA seasonal forecaster + backtest green on full suite" --allow-empty
```

---

## Self-review notes

- **Spec coverage (FA / spec §Component FA):** `Forecast.bands` (Task 1) ✓; seasonal climatology with weekday×tod bins + p10/p50/p90 + thin-bucket→hour-of-day→global fallback (Task 2) ✓; `SeasonalForecaster` per-room broadcast, point=p50 (Task 3) ✓; production wiring via `build_forecaster`, `method="seasonal"` selectable, `"seasonal-naive"` stays a persistence alias (Task 4) ✓; backtest MAPE/RMSE vs persistence + PICP band calibration (Task 5) ✓; real-data backtest sanity run (Task 6) ✓.
- **Deferred to FB/FC (out of scope here):** `Forecast.weather_file` + the real-weather seam (FB); materializing a chosen band level, recommendation schema 1.2, UI Forecast card, and the P2b joint (plant,load) scenarios (FC). The `bands` produced here are what FC consumes.
- **Type consistency:** `seasonal_climatology(loading, times, week_start, n_steps, freq_min, min_samples) -> (point, bands)` used identically in Tasks 2,3,5; `bands` shape `{ITE: {"p10","p50","p90": [...]}}` consistent across Tasks 1,3,5 and the spec; `build_forecaster(method, his, room2ite, his_col_for_room, time_col)` consistent in Task 4 and jobs wiring; `workload_schedules == bands["p50"]` invariant asserted (Task 3) and relied on (Task 5).
- **Backward compatibility:** `bands` defaults None; persistence path and existing forecaster tests unchanged; `build_forecaster` returns the old `StatisticalForecaster` for non-seasonal methods; jobs call sites change construction only (same downstream `forecast()` interface).
- **Point=p50 resolution:** the point series is the p50 band (median), reconciling the spec's "mean"/"p50" wording; documented in File Structure.
