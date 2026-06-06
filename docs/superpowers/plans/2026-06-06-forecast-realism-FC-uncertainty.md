# Forecast Realism FC — Uncertainty Surfacing + P2b Joint (Plant×Load) Scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the seasonal forecast's p10/p50/p90 uncertainty (recommendation schema 1.2 + a web "Forecast" card) and extend P2b's robust stage to **joint (plant, load) scenarios** so the robust winner is feasible under both plant and forecast uncertainty.

**Architecture:** P2b's robust re-rank gains a load dimension. The plant ensemble (`make_scenarios`) is crossed with forecast load bands; each joint scenario evaluates the finalists on a **per-scenario `Forecast` variant** whose `workload_schedules` are the chosen band (`p10`/`p50`/`p90`) — built with `dataclasses.replace`, so the oracle's existing `materialize()` writes the right load and **nothing in the oracle or `materialize` changes**. The expansion is **adaptive**: when the forecast carries bands (FA seasonal), load levels expand to `("p50","p90")`; otherwise it degrades to plant-only (`("p50",)`), preserving P2b behavior and tests. `build_recommendation` adds a schema-1.2 forecast band summary; the Review page shows it. This is phase FC of `docs/superpowers/specs/2026-06-06-forecast-realism-design.md`; **assumes FA + FB have landed** (`Forecast.bands`, `Forecast.weather_file`, seasonal forecaster, the P2b `robust.py`).

**Tech Stack:** Python 3.13, pandas/numpy, FastAPI, React/TS, pytest/vitest, dctwin/EnergyPlus (Docker). Backend tests from `src/`; frontend from `src/frontend`.

---

## Grounding facts (verified against current post-P2b code)

- **`robust.py`**: `make_scenarios(base, n, spread)` (lines 23-33) → `n` `PlantConfig` draws scaling `DEFAULT_PLANT` factors by evenly-spaced multipliers in `[1-spread, 1+spread]` (low multiplier = MORE degraded/hotter plant). `scenario_spread(calibration, ...)` (36-42). `RobustResult` + `robust_select(finalists, scenario_kpis, weights, alpha=0.8)` (68-91) — consumes per-finalist per-scenario KPI lists, returns winner + confidence bands + `n_scenarios`; **no change needed**. `make_oracle_robust_rerank(base_prototxt, oracle_config, calibration, weights, n_scenarios, log_root, oracle_cls=None)` builds `scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)` at construction; its inner `rerank(finalists, forecast)` (≈108-119) loops scenarios → `build_plant_prototxt` → `oracle = oracle_cls(base_prototxt=sproto, project_root=".", config=replace(oracle_config, log_root=...))` → `oracle.evaluate(setpoints, forecast=forecast)` → `per_finalist[i].append(kpi)` → `robust_select(...)`. `robust.py` already imports `from dataclasses import dataclass, replace` and `from planner.plant import build_plant_prototxt, DEFAULT_PLANT, ...`.
- **P2b test** `tests/test_robust.py::test_make_oracle_robust_rerank_runs_scenarios` passes `forecast=None` and asserts `len(_FakeOracle.instances) == 3` for `n_scenarios=3` → FC must keep `forecast=None`/no-bands at **3** scenarios (load levels collapse to one).
- **`Forecast`** (`forecaster.py`, post-FA/FB): `week_start, workload_schedules, method, bands: Optional[dict] (ITE→{p10,p50,p90 per-step}), weather_file`. `materialize(project_root)` writes `workload_schedules` per ITE — **unchanged by FC**.
- **`build_recommendation`** (`recommendation.py:25-77`): params include `forecast_method`, robust block params; the dict has `"forecast": {"method": forecast_method, "weather": "TMY-window"}` and a `"robust"` block; `schema_version` is `"1.1"` when robust present else `"1.0"`.
- **`run_weekly_plan`** (`pipeline.py:23-72`): `forecast = forecaster.forecast(...)` (line 44) → `planner.plan(forecast)` → `robust = robust_rerank_fn(result.beam_finalists, forecast)` → `build_recommendation(..., forecast_method=getattr(forecast,"method",...), robust_*=...)`. `forecast` (with bands + weather_file) is in scope at the `build_recommendation` call.
- **`jobs.py`**: builds `robust_rerank_fn = make_oracle_robust_rerank(...)` and passes it to `run_weekly_plan`. **No FC change needed** (joint expansion is internal + adaptive on `forecast.bands`).
- **Frontend**: `api.ts` `Recommendation` = `{status, setpoints, predicted_kpis, robust?}` (no `forecast` field yet). `Review.tsx` card order: KPI Comparison (~289) → Setpoints (~333) → [robust] Confidence Bands (~383) → [realized] Realized vs Predicted (~421) → Twin Calibration (~467). Insert the Forecast card after Setpoints, before Confidence Bands.

## File Structure

- **Modify** `src/planner/robust.py` — `make_joint_scenarios`, `_band_series`, `_scenario_forecast`; `make_oracle_robust_rerank.rerank` builds adaptive joint scenarios + per-scenario forecast variants.
- **Modify** `src/planner/recommendation.py` — `build_recommendation` schema-1.2 forecast band block.
- **Modify** `src/planner/pipeline.py` — compute the forecast band summary + weather source, pass to `build_recommendation`.
- **Modify** `src/frontend/src/api.ts` + `src/frontend/src/pages/Review.tsx` — `Recommendation.forecast` + a Forecast card.
- **Modify** tests: `src/tests/test_robust.py`, `src/tests/test_recommendation.py`, `src/tests/test_pipeline.py`, `src/frontend/src/pages/Review.test.tsx`; integration `src/tests/integration/test_forecast_realism.py`.

---

## Task 1: Joint-scenario helpers (`robust.py`)

**Files:** Modify `src/planner/robust.py`; Test `src/tests/test_robust.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_robust.py
from planner.robust import make_joint_scenarios, _band_series, _scenario_forecast
from planner.plant import DEFAULT_PLANT
from planner.forecaster import Forecast
from datetime import date


def test_make_joint_scenarios_crosses_plants_and_levels():
    joint = make_joint_scenarios(DEFAULT_PLANT, n_plant=3, spread=0.1, load_levels=("p50", "p90"))
    assert len(joint) == 6                                  # 3 plant draws x 2 load levels
    plant, level = joint[0]
    assert hasattr(plant, "perturbations") and level in ("p50", "p90")
    # every (plant, level) pair present
    assert {lvl for _, lvl in joint} == {"p50", "p90"}


def test_band_series_selects_level_or_falls_back():
    fc = Forecast(week_start=date(2024, 11, 11),
                  workload_schedules={"ite-1": [0.5, 0.5]}, method="seasonal",
                  bands={"ite-1": {"p10": [0.4, 0.4], "p50": [0.5, 0.5], "p90": [0.6, 0.6]}})
    assert _band_series(fc, "p90") == {"ite-1": [0.6, 0.6]}
    # no bands -> returns the point schedules (plant-only fallback)
    fc0 = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]}, method="persistence")
    assert _band_series(fc0, "p90") == {"ite-1": [0.5]}


def test_scenario_forecast_replaces_workload_with_band():
    fc = Forecast(week_start=date(2024, 11, 11),
                  workload_schedules={"ite-1": [0.5]}, method="seasonal",
                  weather_file="w.epw",
                  bands={"ite-1": {"p10": [0.4], "p50": [0.5], "p90": [0.6]}})
    fc90 = _scenario_forecast(fc, "p90")
    assert fc90.workload_schedules == {"ite-1": [0.6]}
    assert fc90.weather_file == "w.epw"                     # other fields preserved
    assert _scenario_forecast(None, "p90") is None          # P2b plant-only path (forecast=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -k "joint or band_series or scenario_forecast" -q`
Expected: FAIL (`cannot import name 'make_joint_scenarios'`).

- [ ] **Step 3: Implement (append to `src/planner/robust.py`)**

```python
def make_joint_scenarios(base, n_plant: int, spread: float, load_levels=("p50",)):
    """Cross n_plant PlantConfig draws with the given load band levels.
    Returns a list of (PlantConfig, level) pairs (length n_plant * len(load_levels))."""
    return [(p, lvl) for p in make_scenarios(base, n_plant, spread) for lvl in load_levels]


def _band_series(forecast, level: str) -> dict:
    """The per-ITE load series for `level` from the forecast bands; falls back to the
    point workload_schedules when the forecast carries no bands (plant-only path)."""
    if forecast is not None and getattr(forecast, "bands", None):
        return {ite: forecast.bands[ite][level] for ite in forecast.bands}
    return forecast.workload_schedules


def _scenario_forecast(forecast, level: str):
    """A per-scenario Forecast whose workload_schedules ARE the chosen band level, so the
    oracle's existing materialize() writes that load. Returns the original forecast (or
    None) unchanged when there are no bands."""
    if forecast is None or not getattr(forecast, "bands", None):
        return forecast
    return replace(forecast, workload_schedules=_band_series(forecast, level))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: PASS (new + all existing robust tests).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/robust.py src/tests/test_robust.py
git commit -m "feat(dtwin): joint-scenario helpers (make_joint_scenarios + per-scenario band forecast)"
```

---

## Task 2: Adaptive joint scenarios in `make_oracle_robust_rerank`

**Files:** Modify `src/planner/robust.py`; Test `src/tests/test_robust.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_robust.py
def test_rerank_expands_to_joint_when_forecast_has_bands(tmp_path, monkeypatch):
    import planner.robust as R
    from planner.oracle import OracleConfig
    from planner.objective import ObjectiveWeights
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    seen_loads = []

    class _Oracle:
        instances = []
        def __init__(self, base_prototxt, config=None, project_root="."):
            _Oracle.instances.append(base_prototxt)
        def evaluate(self, candidates, forecast=None, on_result=None):
            seen_loads.append(forecast.workload_schedules["ite-1"] if forecast else None)
            return [_kpi(100.0, 24.0) for _ in candidates]

    _Oracle.instances = []
    sp = Setpoints(24, 8, 17)
    fc = Forecast(week_start=date(2024, 11, 11), workload_schedules={"ite-1": [0.5]},
                  method="seasonal",
                  bands={"ite-1": {"p10": [0.4], "p50": [0.5], "p90": [0.6]}})
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt",
                                   OracleConfig(n_workers=1, timesteps_per_hour=4, log_root=str(tmp_path)),
                                   None, ObjectiveWeights(), n_scenarios=3, log_root=str(tmp_path),
                                   oracle_cls=_Oracle)
    rr = fn([(sp, _kpi(100, 24), 100.0)], forecast=fc)
    assert rr.n_scenarios == 6                              # 3 plants x {p50,p90}
    assert len(_Oracle.instances) == 6
    # both p50 (0.5) and p90 (0.6) load trajectories were evaluated
    assert [0.5] in seen_loads and [0.6] in seen_loads
```

(The existing `test_make_oracle_robust_rerank_runs_scenarios` — which passes `forecast=None` and asserts 3 — MUST still pass: no bands → load levels collapse to `("p50",)` → 3 scenarios.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -k rerank_expands_to_joint -q`
Expected: FAIL (currently 3 scenarios, no band variants).

- [ ] **Step 3: Implement**

In `src/planner/robust.py` `make_oracle_robust_rerank`: keep building the plant draws once (`plant_scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)`), and rewrite the inner `rerank` to expand to joint scenarios adaptively + use the per-scenario forecast:
```python
    plant_scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)

    def rerank(finalists, forecast):
        from pathlib import Path
        levels = ("p50", "p90") if (forecast is not None and getattr(forecast, "bands", None)) else ("p50",)
        joint = [(p, lvl) for p in plant_scenarios for lvl in levels]
        setpoints = [f[0] for f in finalists]
        per_finalist = [[] for _ in finalists]
        for j, (plant, level) in enumerate(joint):
            sdir = str(Path(log_root) / f"scenario-{j:02d}")
            sproto = build_plant_prototxt(base_prototxt, plant, sdir)
            oracle = oracle_cls(base_prototxt=sproto, project_root=".",
                                config=replace(oracle_config, log_root=str(Path(sdir) / "oracle")))
            fc_j = _scenario_forecast(forecast, level)
            for i, k in enumerate(oracle.evaluate(setpoints, forecast=fc_j)):
                per_finalist[i].append(k)
        return robust_select(finalists, per_finalist, weights)
    return rerank
```
(Replace the existing `scenarios = make_scenarios(...)` line + the old `rerank` body with the above. The construction-time `make_scenarios` stays; only the loop changes from plant-only to adaptive joint.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py tests/test_jobs.py -q`
Expected: PASS — the new joint test (6) AND the existing P2b `test_make_oracle_robust_rerank_runs_scenarios` (3, forecast=None) AND the `test_jobs.py` closure-contract test.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/robust.py src/tests/test_robust.py
git commit -m "feat(dtwin): robust re-rank expands to joint (plant x load-band) scenarios when forecast has bands"
```

---

## Task 3: Recommendation schema 1.2 — forecast band block

**Files:** Modify `src/planner/recommendation.py`; Test `src/tests/test_recommendation.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_recommendation.py
def test_recommendation_forecast_bands_schema_12():
    rec = build_recommendation(
        setpoints=Setpoints(24, 8, 17), kpi=_rk(), week_start=date(2024, 11, 11),
        days=7, forecast_method="seasonal", search_meta={"evals": 10},
        forecast_bands={"p10": 0.42, "p50": 0.5, "p90": 0.61},
        weather_source="Singapore_Changi_Nov2024-Jan2025.epw")
    assert rec["schema_version"] == "1.2"
    assert rec["forecast"]["method"] == "seasonal"
    assert rec["forecast"]["weather"] == "Singapore_Changi_Nov2024-Jan2025.epw"
    assert rec["forecast"]["load_bands"] == {"p10": 0.42, "p50": 0.5, "p90": 0.61}


def test_recommendation_no_forecast_bands_keeps_prior_schema():
    rec = build_recommendation(setpoints=Setpoints(24, 8, 17), kpi=_rk(),
                               week_start=date(2024, 11, 11), days=7,
                               forecast_method="persistence", search_meta={"evals": 10})
    assert rec["schema_version"] == "1.0" and "load_bands" not in rec["forecast"]
```

(`_rk`/`Setpoints`/`date`/`build_recommendation` are imported by the existing recommendation tests; reuse them.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recommendation.py::test_recommendation_forecast_bands_schema_12 -q`
Expected: FAIL (`build_recommendation() got an unexpected keyword argument 'forecast_bands'`).

- [ ] **Step 3: Implement**

In `src/planner/recommendation.py`, add params to `build_recommendation` (after the existing forecast/robust params): `forecast_bands: Optional[dict] = None, weather_source: Optional[str] = None`. Build the `"forecast"` block with the weather source + optional load bands, and bump the schema to 1.2 when bands are present. Replace the current `"forecast": {"method": forecast_method, "weather": "TMY-window"}` entry with a constructed block, and extend the existing schema-version logic:
```python
    forecast_block = {"method": forecast_method, "weather": weather_source or "TMY-window"}
    if forecast_bands is not None:
        forecast_block["load_bands"] = forecast_bands
    ...
    rec["forecast"] = forecast_block
    # schema: 1.2 when forecast bands present, else the existing 1.1/1.0 rule
    if forecast_bands is not None:
        rec["schema_version"] = "1.2"
    elif robust_feasible is not None:
        rec["schema_version"] = "1.1"
```
(Integrate with however the current code sets `schema_version`/the robust block — keep the robust 1.1 bump; forecast bands take precedence to 1.2. `Optional` is already imported.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recommendation.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/recommendation.py src/tests/test_recommendation.py
git commit -m "feat(dtwin): recommendation schema 1.2 forecast load-band block"
```

---

## Task 4: Pipeline passes the forecast band summary + weather source

**Files:** Modify `src/planner/pipeline.py`; Test `src/tests/test_pipeline.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_pipeline.py  (reuse this file's existing request/evaluator/forecaster
# construction; supply a forecaster whose forecast carries bands)
from planner.forecaster import Forecast


def test_run_weekly_plan_surfaces_forecast_bands(make_request_and_mocks):
    request, evaluator, forecaster = make_request_and_mocks
    # wrap the forecaster so its Forecast carries bands (simulate FA seasonal output)
    base = forecaster.forecast(request.week_start, request.days * 96)

    class _Banded:
        def forecast(self, ws, n):
            return Forecast(week_start=ws, workload_schedules=base.workload_schedules,
                            method="seasonal", weather_file="real.epw",
                            bands={ite: {"p10": [x * 0.9 for x in s], "p50": s, "p90": [min(1.0, x * 1.1) for x in s]}
                                   for ite, s in base.workload_schedules.items()})

    rec = run_weekly_plan(request, evaluator, _Banded())
    assert rec["schema_version"] == "1.2"
    assert rec["forecast"]["method"] == "seasonal"
    assert rec["forecast"]["weather"] == "real.epw"
    lb = rec["forecast"]["load_bands"]
    assert lb["p10"] <= lb["p50"] <= lb["p90"]
```

(Mirror the EXACT existing `request/evaluator/forecaster` construction used by the other tests in `test_pipeline.py`; the `make_request_and_mocks` name is illustrative.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_pipeline.py -k surfaces_forecast_bands -q`
Expected: FAIL (no `load_bands` / schema not 1.2).

- [ ] **Step 3: Implement**

In `src/planner/pipeline.py` `run_weekly_plan`, after `forecast = forecaster.forecast(...)`, compute a compact facility aggregate of the bands + the weather source, and pass them to `build_recommendation`. Add near the top of the function (after the forecast is obtained):
```python
    forecast_bands = None
    bands = getattr(forecast, "bands", None)
    if bands:
        import numpy as _np
        forecast_bands = {
            lvl: float(_np.mean([_np.mean(b[lvl]) for b in bands.values()]))
            for lvl in ("p10", "p50", "p90")
        }
    weather_source = None
    wf = getattr(forecast, "weather_file", None)
    if wf:
        from pathlib import Path as _Path
        weather_source = _Path(wf).name
```
and add to the existing `build_recommendation(...)` call:
```python
        forecast_bands=forecast_bands,
        weather_source=weather_source,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_pipeline.py tests/test_recommendation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/pipeline.py src/tests/test_pipeline.py
git commit -m "feat(dtwin): pipeline surfaces forecast load-band summary + weather source"
```

---

## Task 5: Frontend — Forecast card

**Files:** Modify `src/frontend/src/api.ts`, `src/frontend/src/pages/Review.tsx`, `src/frontend/src/pages/Review.test.tsx`.

- [ ] **Step 1: Write the failing test**

```typescript
// In src/frontend/src/pages/Review.test.tsx, add a `forecast` block to the mocked
// getPlan recommendation:
//   forecast: { method: 'seasonal', weather: 'Singapore_Changi_Nov2024-Jan2025.epw',
//               load_bands: { p10: 0.42, p50: 0.5, p90: 0.61 } }
it('shows the Forecast card with method, weather and load bands', async () => {
  render(<Review planId="plan-1" />);   // match the existing render signature
  expect(await screen.findByText(/Forecast/i)).toBeInTheDocument();
  expect(await screen.findByText(/seasonal/i)).toBeInTheDocument();
  expect(await screen.findByText(/Singapore_Changi/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run test -- --run src/pages/Review.test.tsx 2>&1 | tail -6`
Expected: FAIL (no Forecast card / `seasonal` text).

- [ ] **Step 3: Implement**

In `src/frontend/src/api.ts`, extend `Recommendation` with an optional forecast block:
```typescript
  forecast?: {
    method: string;
    weather: string;
    load_bands?: { p10: number; p50: number; p90: number };
  } | null;
```
In `src/frontend/src/pages/Review.tsx`: extract `const forecast = rec?.forecast;`. Render a **"Forecast"** card after the Setpoints card and before the Confidence Bands card, reusing the existing `bracket-card`/table styling: show `forecast.method`, `forecast.weather` (the EPW/weather source), and when `forecast.load_bands` exists a small p10/p50/p90 row (each `?.toFixed(2) ?? '—'`). Guard the whole card on `forecast` being present (older plans without it show nothing).

- [ ] **Step 4: Build + test**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: build clean; all pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/frontend/src/api.ts src/frontend/src/pages/Review.tsx src/frontend/src/pages/Review.test.tsx
git commit -m "feat(dtwin): web Forecast card (method + weather source + load bands)"
```

---

## Task 6: Docker integration — full forecast realism (FA+FB+FC)

**Files:** Create `src/tests/integration/test_forecast_realism.py`.

- [ ] **Step 1: Write the marked integration test**

```python
# src/tests/integration/test_forecast_realism.py
import json
from datetime import date
from pathlib import Path
import pickle
import pandas as pd
import pytest

pytestmark = pytest.mark.integration

REAL_EPW = "data/weather/Singapore_Changi_Nov2024-Jan2025.epw"


def test_joint_robust_rerank_on_seasonal_forecast_and_real_weather(tmp_path):
    """End-to-end: seasonal forecast (with bands) + real EPW + joint (plant x load)
    robust re-rank of 2 finalists on a 1-day within-year window."""
    from planner.robust import make_oracle_robust_rerank, RobustResult
    from planner.oracle import OracleConfig
    from planner.forecaster import build_forecaster
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    assert Path(REAL_EPW).exists()
    his = pd.read_csv("data/his_data_processed.csv")
    room2ite = json.loads(Path("configs/dt/room2ite_map.json").read_text())
    cfg = pickle.loads(Path("models/forecaster.pkl").read_bytes())
    forecaster = build_forecaster("seasonal", his, room2ite, cfg["his_col_for_room"],
                                  weather_file=REAL_EPW)
    forecast = forecaster.forecast(date(2024, 11, 11), 1 * 96)     # 1 day, 15-min
    assert forecast.bands and forecast.weather_file == REAL_EPW

    def _k():
        return WeeklyKPI(0.0, 1.2, 25.0, 0, 0, True, 0.0, 0.0, 0.0)
    finalists = [(Setpoints(20.0, 7.05, 13.0), _k(), 0.0),
                 (Setpoints(22.0, 7.05, 14.0), _k(), 0.0)]
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt",
                                   OracleConfig(n_workers=1, timesteps_per_hour=4,
                                                log_root=str(tmp_path / "oracle")),
                                   None, ObjectiveWeights(), n_scenarios=2, log_root=str(tmp_path))
    rr = fn(finalists, forecast=forecast)
    assert isinstance(rr, RobustResult)
    assert rr.n_scenarios == 4                                     # 2 plants x {p50,p90}
    assert "inlet_temp_max_c" in rr.confidence_bands
```

(Verify the `WeeklyKPI(...)` positional order matches `types.py`; use keywords if unsure. If `models/forecaster.pkl` may be persistence-built, the test builds the seasonal forecaster explicitly via `build_forecaster("seasonal", ...)`.)

- [ ] **Step 2: Run it under Docker**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_forecast_realism.py -m integration -q"`
Expected: PASS (2 plants × 2 load levels × 2 finalists = 8 short EnergyPlus runs on the real EPW; several minutes). Auto-deselected in the normal suite.

- [ ] **Step 3: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/tests/integration/test_forecast_realism.py
git commit -m "test(dtwin): integration — seasonal forecast + real weather + joint robust re-rank"
```

---

## Task 7: Full-suite verification

- [ ] **Step 1: Full backend + frontend**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q 2>&1 | tail -2`
Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: all backend pass (incl. the new robust/recommendation/pipeline tests + the P2b tests still green), frontend build clean + all pass.

- [ ] **Step 2: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add -A && git commit -m "test(dtwin): FC uncertainty + joint scenarios green on full suite" --allow-empty
```

---

## Self-review notes

- **Spec coverage (FC / spec §Component FC):** joint (plant, load) scenarios via `make_joint_scenarios` + per-scenario forecast variants (Tasks 1-2) ✓; worst-case feasibility + CVaR over the joint ensemble (reuses `robust_select`, unchanged) ✓; schema-1.2 forecast band block (Task 3) ✓; pipeline surfaces the band summary + weather source (Task 4) ✓; web Forecast card (Task 5) ✓; end-to-end integration combining FA+FB+FC (Task 6) ✓.
- **The correlated stress case** (degraded plant + p90 load) is in the joint set: `make_scenarios` includes the low-multiplier (most-degraded) plant, crossed with `p90` load → `robust_select`'s worst-case feasibility gate sees it.
- **Type consistency:** `make_joint_scenarios(base, n_plant, spread, load_levels) -> list[(PlantConfig, str)]`, `_band_series(forecast, level) -> dict`, `_scenario_forecast(forecast, level) -> Forecast|None` consistent across Tasks 1-2; `forecast_bands` shape `{p10,p50,p90}` (floats) + `weather_source` consistent across recommendation (Task 3), pipeline (Task 4), api.ts/Review (Task 5); `RobustResult.n_scenarios` = J (plants × levels).
- **Backward compatibility (critical):** the joint expansion is **adaptive** — `forecast=None`/no-bands → `load_levels=("p50",)` → exactly the P2b plant-only ensemble (the P2b `test_make_oracle_robust_rerank_runs_scenarios` stays at 3); `_scenario_forecast(None, ...)` returns `None`; `robust_select`/`make_scenarios`/oracle/`materialize` unchanged; schema stays 1.1/1.0 when no forecast bands; the Forecast card hides for older plans. No `jobs.py` change needed.
- **No oracle/materialize change:** per-scenario load is injected by swapping `workload_schedules` on a `replace`-d `Forecast`, so the oracle's existing internal `materialize()` writes the right band — avoiding the overwrite hazard of a `materialize(band_level=...)` approach.
