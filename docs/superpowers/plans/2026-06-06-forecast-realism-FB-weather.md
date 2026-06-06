# Forecast Realism FB — Per-Forecast Real-Weather Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the EnergyPlus simulation with a per-forecast real weather EPW (the user-provided `Singapore_Changi_Nov2024-Jan2025.epw`) instead of the static 1989-90 TMY, for any planning week within the EPW's coverage.

**Architecture:** A weather file path is carried on `Forecast.weather_file` (sourced from `forecaster.pkl`), threaded through the oracle into `write_week_config`, which sets the prototxt's `eplus_env_config.weather_file` before serialization. Because the real EPW has exactly one of each calendar month, EnergyPlus reads the real weather by RunPeriod month/day with no engine change; an EPW-coverage check guards against requesting a week outside the file. **Within-year weeks only** (the existing cross-year rejection stays); cross-year weeks remain a documented Tier-2 follow-up (they need new proto year fields + a dctwin core change — see "Deferred"). This is phase FB of `docs/superpowers/specs/2026-06-06-forecast-realism-design.md`; **assumes FA has landed** (it references `Forecast`, `StatisticalForecaster`, `SeasonalForecaster`, `build_forecaster`).

**Tech Stack:** Python 3.13, protobuf (`dctwin.utils.read_engine_config` / `google.protobuf.text_format`), dctwin/EnergyPlus 9.5 (Docker), pytest. Backend tests from `src/`: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest`.

---

## Grounding facts (verified against current code)

- **`write_week_config`** (`planner/week_config.py:32-58`): `write_week_config(base_prototxt, week_start, out_path, days=7, timesteps_per_hour=None) -> str`. Body: `period = compute_week_period(week_start, days)`; `cfg = read_engine_config(str(base_prototxt))`; `env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))`; `stc = env_cfg.simulation_time_config`; sets `stc.begin_month/begin_day_of_month/end_month/end_day_of_month` (+ `number_of_timesteps_per_hour` if given); `Path(out_path).write_text(text_format.MessageToString(cfg))`. **Never sets `weather_file`.**
- **`compute_week_period`** (`week_config.py:17-29`): builds `WeekPeriod(begin_month, begin_day, end_month, end_day)`; **lines 25-28 reject cross-year**: `if end.year != week_start.year: raise ValueError(f"week {week_start}..{end} crosses a year boundary; not supported in v1")`.
- **Proto** (`dctwin/utils/protos/dt_engine.proto`): `EPlusEnvConfig.weather_file` is an **optional top-level string** (field 3); `SimulationTimeConfig` has **only month/day fields — no year, no day-of-week**.
- **dt.prototxt** (`configs/dt/dt.prototxt`): `eplus_env_config { weather_file: "data/weather/SGP_Singapore.486980_IWEC.epw" ... simulation_time_config { begin_month: 11 begin_day_of_month: 6 end_month: 12 end_day_of_month: 31 number_of_timesteps_per_hour: 4 } }`. Path is relative to project root.
- **Year 2013 is hardcoded in the dctwin engine** (`dctwin/third_parties/eplus/core.py:72,75`, `_get_one_episode_len`) for the **episode-duration** datetime calc only — year-agnostic for within-year weeks. The actual weather rows are selected by month/day, and the real EPW has one Nov/Dec/Jan, so the real weather is used without a year field. (Cross-year is the only case this breaks — see Deferred.)
- **Weather copy** (`core.py:171-177`): `shutil.copy(config.eplus.weather_file, case_dir/<basename>)` — whatever `eplus_env_config.weather_file` points to is copied into the Docker case dir.
- **Oracle** (`oracle.py:50-69`): in `evaluate`, after `forecast.materialize(...)`, when `forecast.week_start` exists it calls `write_week_config(self.base_prototxt, forecast.week_start, week_cfg_path, timesteps_per_hour=cfg.timesteps_per_hour)`.
- **Real EPW** (`data/weather/Singapore_Changi_Nov2024-Jan2025.epw`): NASA-POWER, Singapore Changi, hourly, Nov 1 2024 → Jan 31 2025; `DATA PERIODS` line (line 8): `DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31`.
- **forecaster.pkl** (`fit_forecaster.py:42-56`): config dict `{method, his_csv, room2ite_path, his_col_for_room}`; FB adds `weather_file`.
- **FA-added symbols** (assumed present): `Forecast.bands`; `StatisticalForecaster`/`SeasonalForecaster`; `build_forecaster(method, his, room2ite, his_col_for_room, time_col)`.

## File Structure

- **Modify** `src/planner/forecaster.py` — `Forecast.weather_file` field; `weather_file` ctor arg on `StatisticalForecaster` + `SeasonalForecaster` (threaded into the returned `Forecast`); `build_forecaster` passes it through.
- **Create** `src/planner/epw.py` — `epw_data_period(path)` + `week_within_epw(weather_file, week_start, days)` coverage check.
- **Modify** `src/planner/week_config.py` — `write_week_config(..., weather_file=None)` sets `env_cfg.weather_file` + validates coverage.
- **Modify** `src/planner/oracle.py` — pass `forecast.weather_file` to `write_week_config`.
- **Modify** `src/fit_forecaster.py` — `weather_file` config key.
- **Modify** `src/webapp/jobs.py` — thread `fc_cfg.get("weather_file")` into `build_forecaster`.
- **Modify** tests: `src/tests/test_forecaster.py`, `src/tests/test_week_config.py`; **create** `src/tests/test_epw.py`; integration `src/tests/integration/test_real_weather.py`.

---

## Task 1: `Forecast.weather_file` field + forecaster threading

**Files:** Modify `src/planner/forecaster.py`; Test `src/tests/test_forecaster.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_forecaster.py
def test_forecast_carries_weather_file():
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]},
                  method="seasonal", weather_file="data/weather/real.epw")
    assert fc.weather_file == "data/weather/real.epw"


def test_forecasters_thread_weather_file_into_forecast():
    col = "1F_Datahall 2A 1F Data Hall 2A IT loads"
    df = pd.DataFrame({col: [900.0] * 8})
    room2ite = {"Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1_800_000.0}}}
    hcr = {"Data Hall 1F 2A": col}
    fc = StatisticalForecaster(df, room2ite, hcr, method="persistence",
                               weather_file="data/weather/real.epw")
    out = fc.forecast(week_start=date(2024, 11, 11), n_steps=4)
    assert out.weather_file == "data/weather/real.epw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py::test_forecast_carries_weather_file tests/test_forecaster.py::test_forecasters_thread_weather_file_into_forecast -q`
Expected: FAIL (`__init__() got an unexpected keyword argument 'weather_file'`).

- [ ] **Step 3: Implement**

In `src/planner/forecaster.py`:
(a) add the field to `Forecast` (after `bands`):
```python
    bands: Optional[dict] = None
    weather_file: Optional[str] = None   # per-forecast EPW path (FB)
```
(b) `StatisticalForecaster.__init__` — add `weather_file: Optional[str] = None` (after `method="persistence"`) and store `self.weather_file = weather_file`; in `forecast()` change the return to `Forecast(week_start=week_start, workload_schedules=schedules, method=self.method, weather_file=self.weather_file)`.
(c) `SeasonalForecaster.__init__` — add `weather_file: Optional[str] = None` (after `min_samples`) and store `self.weather_file`; in `forecast()` add `weather_file=self.weather_file` to the `Forecast(...)` return.
(d) `build_forecaster(method, his_data, room2ite, his_col_for_room, time_col="_time", weather_file=None)` — pass `weather_file` to both constructors:
```python
def build_forecaster(method, his_data, room2ite, his_col_for_room, time_col="_time", weather_file=None):
    if method == "seasonal":
        return SeasonalForecaster(his_data, room2ite, his_col_for_room,
                                  time_col=time_col, weather_file=weather_file)
    return StatisticalForecaster(his_data, room2ite, his_col_for_room,
                                 method=method, weather_file=weather_file)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_forecaster.py -q`
Expected: PASS (new + all existing forecaster tests; `weather_file` defaults None).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/forecaster.py src/tests/test_forecaster.py
git commit -m "feat(dtwin): Forecast.weather_file threaded through forecasters + factory"
```

---

## Task 2: EPW coverage check (`epw.py`)

**Files:** Create `src/planner/epw.py`; Test `src/tests/test_epw.py`.

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_epw.py
from datetime import date
from planner.epw import epw_data_period, week_within_epw

_HEADER = (
    "LOCATION,Singapore Changi,-,SGP,NASA POWER,486980,1.367,103.983,8.0,16.0\n"
    "DESIGN CONDITIONS,0\nTYPICAL/EXTREME PERIODS,0\nGROUND TEMPERATURES,0\n"
    "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0\nCOMMENTS 1,\nCOMMENTS 2,\n"
    "DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31\n"
)


def _write_epw(tmp_path):
    p = tmp_path / "w.epw"
    p.write_text(_HEADER + "2024,11,1,1,60,_,27.1\n")
    return str(p)


def test_epw_data_period_parses_start_end(tmp_path):
    assert epw_data_period(_write_epw(tmp_path)) == ((11, 1), (1, 31))


def test_week_within_epw_handles_year_wrap(tmp_path):
    epw = _write_epw(tmp_path)
    assert week_within_epw(epw, date(2024, 11, 11), days=7) is True    # Nov within Nov-Jan
    assert week_within_epw(epw, date(2025, 1, 10), days=7) is True     # Jan within
    assert week_within_epw(epw, date(2024, 6, 1), days=7) is False     # June outside
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_epw.py -q`
Expected: FAIL (`No module named 'planner.epw'`).

- [ ] **Step 3: Implement (create `src/planner/epw.py`)**

```python
"""Lightweight EPW coverage check — read the DATA PERIODS line to know which
(month, day) range the weather file covers, so we never request a week outside it."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


def epw_data_period(weather_file: str) -> tuple:
    """Return ((start_month, start_day), (end_month, end_day)) from the EPW's
    'DATA PERIODS' header line (line 8). Fields look like ' 11/ 1' and ' 1/31'."""
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
    return md >= start or md <= end          # wraps year-end (e.g. Nov 1 .. Jan 31)


def week_within_epw(weather_file: str, week_start: date, days: int = 7) -> bool:
    """True if every day of the week falls within the EPW's data period."""
    start, end = epw_data_period(weather_file)
    for i in range(days):
        d = week_start + timedelta(days=i)
        if not _md_in_range((d.month, d.day), start, end):
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_epw.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/epw.py src/tests/test_epw.py
git commit -m "feat(dtwin): EPW coverage check (epw_data_period + week_within_epw)"
```

---

## Task 3: `write_week_config` sets the weather file + validates coverage

**Files:** Modify `src/planner/week_config.py`; Test `src/tests/test_week_config.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_week_config.py  (mirror the existing import of write_week_config
# + read_engine_config used by current tests in this file)
from datetime import date
from planner.week_config import write_week_config
from dctwin.utils import read_engine_config


def test_write_week_config_sets_weather_file(tmp_path):
    out = tmp_path / "week.prototxt"
    # base prototxt is the project default; weather_file overrides the static TMY
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7,
                      weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")
    cfg = read_engine_config(str(out))
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert env.weather_file == "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"
    assert env.simulation_time_config.begin_month == 11
    assert env.simulation_time_config.begin_day_of_month == 11


def test_write_week_config_rejects_week_outside_epw_coverage(tmp_path):
    import pytest
    out = tmp_path / "week.prototxt"
    with pytest.raises(ValueError, match="outside the weather file coverage"):
        write_week_config("configs/dt/dt.prototxt", date(2024, 6, 1), str(out), days=7,
                          weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")


def test_write_week_config_without_weather_file_unchanged(tmp_path):
    out = tmp_path / "week.prototxt"
    write_week_config("configs/dt/dt.prototxt", date(2024, 11, 11), str(out), days=7)
    cfg = read_engine_config(str(out))
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert env.weather_file.endswith("IWEC.epw")   # static TMY untouched
```

(If the existing `test_week_config.py` uses a different base prototxt path or helper, mirror it; the assertions on `env.weather_file` are the point.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_week_config.py -q`
Expected: FAIL (`write_week_config() got an unexpected keyword argument 'weather_file'`).

- [ ] **Step 3: Implement**

In `src/planner/week_config.py`: add `weather_file: Optional[str] = None` to the `write_week_config` signature (after `timesteps_per_hour`); ensure `Optional` is imported. After `env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))` and before writing, insert:
```python
    if weather_file is not None:
        from planner.epw import week_within_epw
        if not week_within_epw(weather_file, week_start, days):
            raise ValueError(
                f"week {week_start} (+{days}d) is outside the weather file coverage of {weather_file}")
        env_cfg.weather_file = weather_file
```
(`compute_week_period`'s existing cross-year `ValueError` still guards within-year — FB does not change it; see Deferred.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_week_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/week_config.py src/tests/test_week_config.py
git commit -m "feat(dtwin): write_week_config sets per-forecast weather_file + validates EPW coverage"
```

---

## Task 4: Oracle threads `forecast.weather_file`

**Files:** Modify `src/planner/oracle.py`; Test `src/tests/test_oracle.py` (or wherever oracle is unit-tested without Docker).

- [ ] **Step 1: Write the failing test**

```python
# append to the oracle unit test file (it tests write_week_config wiring without Docker;
# if none exists, add this to tests/test_week_config.py as an oracle-seam test).
def test_oracle_passes_weather_file_to_week_config(tmp_path, monkeypatch):
    import planner.oracle as O
    from planner.forecaster import Forecast
    from datetime import date

    captured = {}
    def fake_wwc(base, week_start, out_path, days=7, timesteps_per_hour=None, weather_file=None):
        captured["weather_file"] = weather_file
        return str(out_path)
    monkeypatch.setattr(O, "write_week_config", fake_wwc)

    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={}, method="seasonal",
                  weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")
    # call only the week-config-writing portion of evaluate via the smallest seam available;
    # if evaluate() can't run without Docker, factor the write_week_config call into a helper
    # `_write_week_cfg(self, forecast)` and test that helper directly.
    O.ParallelEnvOracle("configs/dt/dt.prototxt")._write_week_cfg(fc, str(tmp_path / "w.prototxt"))
    assert captured["weather_file"] == "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_week_config.py -k oracle_passes_weather_file -q`
Expected: FAIL (`_write_week_cfg` missing / `weather_file` not threaded).

- [ ] **Step 3: Implement**

In `src/planner/oracle.py`, in `evaluate`, change the existing call (currently `write_week_config(self.base_prototxt, forecast.week_start, week_cfg_path, timesteps_per_hour=cfg.timesteps_per_hour)`) to also pass the weather file. Extract the call into a small helper so it is unit-testable without Docker:
```python
    def _write_week_cfg(self, forecast, week_cfg_path):
        return write_week_config(
            self.base_prototxt, forecast.week_start, week_cfg_path,
            timesteps_per_hour=self.config.timesteps_per_hour,
            weather_file=getattr(forecast, "weather_file", None))
```
and call `self._write_week_cfg(forecast, week_cfg_path)` where the inline `write_week_config(...)` currently is. (Use the same `timesteps_per_hour` source the current code uses — `self.config.timesteps_per_hour`; match the existing attribute.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_week_config.py tests/test_oracle.py -q 2>&1 | tail -3`
Expected: PASS (the new oracle-seam test + existing oracle/week_config tests). `import planner.oracle` clean.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/oracle.py src/tests/test_week_config.py
git commit -m "feat(dtwin): oracle threads forecast.weather_file into write_week_config"
```

---

## Task 5: Config + production wiring (`fit_forecaster.py` + `jobs.py`)

**Files:** Modify `src/fit_forecaster.py`, `src/webapp/jobs.py`; Test `src/tests/test_fit_forecaster.py` (or `test_jobs.py`).

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_fit_forecaster.py (or test_jobs.py if fit_forecaster has no test file)
import pickle
from pathlib import Path
import fit_forecaster


def test_fit_forecaster_records_weather_file(tmp_path, monkeypatch):
    monkeypatch.chdir("/mnt/lv/home/hoanghuy/newcode/dctwin/src")   # real CSV + room2ite
    out = tmp_path / "fc.pkl"
    fit_forecaster.main(method="seasonal", out_path=str(out),
                        weather_file="data/weather/Singapore_Changi_Nov2024-Jan2025.epw")
    cfg = pickle.loads(Path(out).read_bytes())
    assert cfg["method"] == "seasonal"
    assert cfg["weather_file"] == "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_fit_forecaster.py::test_fit_forecaster_records_weather_file -q`
Expected: FAIL (`main() got an unexpected keyword argument 'weather_file'`).

- [ ] **Step 3: Implement**

In `src/fit_forecaster.py` `main`, add a `weather_file: str | None = None` parameter and include it in the config dict:
```python
def main(his_csv: str = "data/his_data_processed.csv",
         room2ite_path: str = "configs/dt/room2ite_map.json",
         method: str = "persistence",
         out_path: str = "models/forecaster.pkl",
         weather_file: str | None = None) -> None:
    ...
    config = {
        "method": method,
        "his_csv": his_csv,
        "room2ite_path": room2ite_path,
        "his_col_for_room": his_col_for_room,
        "weather_file": weather_file,
    }
```
In `src/webapp/jobs.py`, in both `run_plan_job` and `run_deploy_job`, pass the configured weather file into the factory:
```python
    forecaster = build_forecaster(fc_cfg["method"], his, room2ite, fc_cfg["his_col_for_room"],
                                  weather_file=fc_cfg.get("weather_file"))
```
(`.get` keeps old pickles without the key working — `weather_file` defaults to None → static TMY.)

- [ ] **Step 4: Run tests to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_fit_forecaster.py tests/test_jobs.py -q && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "import webapp.jobs"`
Expected: PASS + clean import.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/fit_forecaster.py src/webapp/jobs.py src/tests/test_fit_forecaster.py
git commit -m "feat(dtwin): forecaster.pkl carries weather_file; jobs thread it into the forecaster"
```

---

## Task 6: Docker integration — real weather on a real week

**Files:** Create `src/tests/integration/test_real_weather.py`.

- [ ] **Step 1: Write the marked integration test**

```python
# src/tests/integration/test_real_weather.py
from datetime import date
from pathlib import Path
import pytest

pytestmark = pytest.mark.integration

REAL_EPW = "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"


def test_oracle_runs_on_real_weather_within_year(tmp_path):
    """A 1-day within-year week runs EnergyPlus against the REAL provided EPW."""
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.forecaster import Forecast
    from planner.types import Setpoints

    assert Path(REAL_EPW).exists(), "the user-provided real EPW must be present"
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={}, method="seasonal",
                  weather_file=REAL_EPW)
    oracle = ParallelEnvOracle("configs/dt/dt.prototxt", project_root=".",
                               config=OracleConfig(n_workers=1, timesteps_per_hour=4,
                                                   log_root=str(tmp_path / "oracle")))
    kpis = oracle.evaluate([Setpoints(22.0, 7.05, 14.0)], forecast=fc)
    assert len(kpis) == 1 and kpis[0].total_hvac_energy_kwh >= 0.0
    # the written week config must reference the real EPW (proves the seam end-to-end)
    wk = list(Path(tmp_path).rglob("*week*.prototxt")) or list(Path(tmp_path).rglob("*.prototxt"))
    assert any("Singapore_Changi" in p.read_text() for p in wk)
```

(If `Forecast.workload_schedules={}` would leave no IT-load JSON for the sim, mirror the existing `tests/integration/test_plan_weekly.py` forecaster setup to materialize a minimal real-history forecast for the week instead; the assertion that matters is that the run uses the real EPW.)

- [ ] **Step 2: Run it under Docker**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_real_weather.py -m integration -q"`
Expected: PASS (one short EnergyPlus run on the real EPW; a few minutes). Auto-deselected in the normal suite.

- [ ] **Step 3: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/tests/integration/test_real_weather.py
git commit -m "test(dtwin): integration — EnergyPlus runs on the real provided EPW (within-year)"
```

---

## Task 7: Full-suite verification

- [ ] **Step 1: Full backend + frontend**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q 2>&1 | tail -2`
Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: all backend pass (+ the new epw/weather tests; integration deselected), frontend unchanged + green.

- [ ] **Step 2: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add -A && git commit -m "test(dtwin): FB real-weather seam green on full suite" --allow-empty
```

---

## Deferred — Tier 2: cross-year weeks (NOT in FB)

A planning week that straddles Dec 31 → Jan 1 (e.g. `week_start=2024-12-30`) is still rejected by `compute_week_period` (`week_config.py:25-28`). Supporting it requires changes to **dctwin internals**, out of FB scope:

1. Add `optional int32 begin_year` / `end_year` to `SimulationTimeConfig` in `dctwin/utils/protos/dt_engine.proto` and **regenerate** the protobuf Python bindings (build step).
2. Set `stc.begin_year = week_start.year` / `stc.end_year = end.year` in `write_week_config` and **replace** the cross-year `ValueError` with the EPW-coverage check.
3. Change `dctwin/third_parties/eplus/core.py:72,75` (`_get_one_episode_len`) to read the year from the config/RunPeriod instead of hardcoding 2013, so the episode-duration datetime calc spans the year boundary.

This is a vendored-engine change with protobuf regeneration and EnergyPlus day-of-week/leap-year edge cases — its own spec/plan if needed. The operational period is overwhelmingly within-year (only weeks starting ~Dec 25–31 are affected), so FB delivers real-weather realism for the bulk of it without this risk.

---

## Self-review notes

- **Spec coverage (FB / spec §Component FB):** per-forecast `weather_file` on `Forecast` (Task 1) ✓; `write_week_config` sets `env_cfg.weather_file` (Task 3) ✓; coverage validation replacing silent wrong-weather (Tasks 2–3) ✓; oracle threading (Task 4) ✓; config + production wiring (Task 5) ✓; validated against the **real provided EPW** (Task 6) ✓. **Divergence from spec:** the spec's "lift the cross-year rejection / RunPeriod Begin+End year" is **descoped to Tier 2** (Deferred) because grounding showed it needs dctwin proto + engine-core changes; FB ships within-year real weather, which covers the operational period bar weeks straddling year-end.
- **Type consistency:** `weather_file: Optional[str]` consistent on `Forecast`, both forecasters, `build_forecaster`, `write_week_config`, and the `fc_cfg["weather_file"]` key (Tasks 1,3,5); `week_within_epw(weather_file, week_start, days)` / `epw_data_period(weather_file)` consistent (Tasks 2,3).
- **Backward compatibility:** `weather_file` defaults None everywhere → static IWEC TMY + existing tests unchanged; `fc_cfg.get("weather_file")` tolerates old pickles; cross-year rejection unchanged.
- **EnergyPlus correctness:** within-year weeks select real weather by month/day (the EPW has one Nov/Dec/Jan); the 2013 duration hardcode is year-agnostic for within-year spans; day-of-week labeling may differ but IT load comes from the (correctly day-aligned) FA forecast via ExternalInterface, not IDF weekday schedules.
