# Fidelity Loop P2a — Calibration + Uncertainty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Learn a per-KPI residual correction (+ uncertainty) from the deploy loop's paired predicted-vs-realized history, apply it as a bias-corrected objective during planning so the twin's predictions track the (perturbed) plant, and surface the calibration state via API + UI.

**Architecture:** P1 already deploys the perturbed plant and records realized KPIs. P2a adds: (1) a **paired** (predicted, realized) history written at deploy time (`data/calibration_history.json`); (2) a pure `Calibrator` that fits per-KPI additive bias + sigma → a `Calibration` persisted to `data/calibration.json`; (3) a **corrected objective** — `BeamPlanner` applies `Calibration.apply(kpi)` before scoring, so the search optimizes against bias-corrected predictions; (4) recompute-on-deploy; (5) `GET /api/calibration` + a small UI display. Everything is additive and backward-compatible (no calibration file → identity → today's behavior). This is P2a of `docs/superpowers/specs/2026-06-06-closing-fidelity-loop-design.md`; **P2b (scenario/ensemble-robust selection) + P2c (recalibrator seam) are a follow-up plan.**

**Tech Stack:** Python 3.13, FastAPI, React/TS, pytest/vitest. Run backend tests from `src/`: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest`. Frontend from `src/frontend`: `npm run build && npm run test -- --run`.

---

## Grounding facts (verified against the merged code — use these exact names)

- **predicted_kpis keys** (`recommendation.py:52-58`): `total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max_c` (note `_c`), `inlet_violation_steps`, `energy_reduction_vs_baseline_pct` (nullable).
- **realized_kpis keys** (`deploy.py:46-51`): `total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max_c`, `inlet_violation_steps`.
- **`WeeklyKPI` fields** (`types.py:49-62`): `total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max` (NO `_c`), `inlet_violation_steps`, `rh_violation_steps`, `feasible`, `inlet_excess_degc_steps`, `rh_excursion_steps`, `zone_temp_band_steps`. **It is a frozen dataclass** → use `dataclasses.replace`.
- **Objective** (`objective.py`): `INFEASIBLE = math.inf` (line 8); `score(kpi, w) -> float`; `is_feasible(kpi, w) -> bool`; `ObjectiveWeights` frozen (lambda_temp=1.0, lambda_rh=0.2, lambda_zone=0.1, inlet_tol_steps=0, rh_hard=False).
- **`BeamPlanner`** (`beam_search.py`): `__init__(self, space, evaluator, weights=None, config=None)`; `_score_batch(self, candidates, forecast, on_result=None)` does `kpis = self.evaluator.evaluate(candidates, forecast, on_result=on_result)` then `return [(c, k, score(k, self.weights)) for c, k in zip(candidates, kpis)]`.
- **`run_weekly_plan`** (`pipeline.py:23-59`): builds `BeamPlanner(space, evaluator, weights, beam)` then `planner.plan(forecast, on_level=on_level, on_eval=on_eval)`; the best candidate's `WeeklyKPI` flows into `build_recommendation`.
- **`run_deploy_job`** (`jobs.py:142-184`): after `rec = deploy(rec_path, plant_oracle, forecast=forecast)`, `rec` holds BOTH `rec["predicted_kpis"]` (from recommendation.json, loaded at line ~161) AND `rec["realized_kpis"]`; currently it calls `store.save_realized(...)` + `advance_history(rec["realized_kpis"], week_start, "data/realized_history.csv")`.
- **`advance_history`** (`history.py:16-29`): `advance_history(realized: dict, week_start: date, his_csv: str)`, idempotent per `week_start`.
- **`PlanStore`** (`store.py`): `plan_dir`, `save_recommendation`/`get_recommendation`, `save_realized`/`get_realized`.
- **API** (`main.py`): `create_app(...)`; `operator = auth.require("operator")`; `get_plan` at lines ~52-59 returns `{plan_id, status, recommendation, realized}`.
- **Frontend** (`api.ts`): `req()` client; `PlanDetail`/`Recommendation` interfaces; `Review.tsx` KPI tables ~280-417.

## File Structure

- **Create** `src/planner/calibrator.py` — `Calibration` (bias/sigma/n_weeks + `apply`/`sigma_for`/`to_dict`/`from_dict`/`identity`), `fit_calibration`, `load_calibration`, `save_calibration`, `recompute_calibration`, `CALIB_KEYS`.
- **Create** `src/tests/test_calibrator.py`.
- **Modify** `src/planner/history.py` — add `advance_calibration(predicted, realized, week_start, path)`.
- **Modify** `src/tests/test_history.py` — test `advance_calibration`.
- **Modify** `src/planner/beam_search.py` — `BeamPlanner` accepts an optional `calibration`; `_score_batch` applies it before scoring.
- **Modify** `src/planner/pipeline.py` — `run_weekly_plan` gains `calibration=None`, threads it to `BeamPlanner`.
- **Modify** `src/tests/test_beam_search.py` (or test_pipeline) — corrected-objective behavior test.
- **Modify** `src/webapp/jobs.py` — `run_deploy_job` writes paired history + recomputes calibration; `run_plan_job` loads calibration + passes to `run_weekly_plan`.
- **Modify** `src/webapp/main.py` — `GET /api/calibration` (operator).
- **Modify** `src/tests/test_api.py` — calibration endpoint test.
- **Modify** `src/frontend/src/api.ts` + `src/frontend/src/pages/Review.tsx` (+ test) — `getCalibration` + a small calibration panel.

---

## Task 1: Calibration model + fit (`calibrator.py`)

**Files:** Create `src/planner/calibrator.py`; Test `src/tests/test_calibrator.py`.

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_calibrator.py
import math
from planner.calibrator import Calibration, fit_calibration, CALIB_KEYS
from planner.types import WeeklyKPI


def _kpi(energy=100.0, pue=1.2, inlet=24.0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=pue, inlet_temp_max=inlet,
                     inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                     inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0,
                     zone_temp_band_steps=0.0)


def test_fit_calibration_bias_and_sigma():
    # realized consistently 2 kWh higher + inlet 1.0 C higher than predicted
    hist = [
        {"week_start": "2013-11-04",
         "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
         "realized":  {"total_hvac_energy_kwh": 102.0, "pue_mean": 1.2, "inlet_temp_max_c": 25.0}},
        {"week_start": "2013-11-11",
         "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
         "realized":  {"total_hvac_energy_kwh": 104.0, "pue_mean": 1.2, "inlet_temp_max_c": 25.0}},
    ]
    cal = fit_calibration(hist)
    assert cal.n_weeks == 2
    assert cal.bias["total_hvac_energy_kwh"] == 3.0          # mean(2,4)
    assert cal.bias["inlet_temp_max_c"] == 1.0              # mean(1,1)
    assert math.isclose(cal.sigma["total_hvac_energy_kwh"], 1.0)  # std of (2,4)=1.0
    assert cal.sigma["inlet_temp_max_c"] == 0.0


def test_fit_calibration_identity_when_empty():
    cal = fit_calibration([])
    assert cal.n_weeks == 0
    assert cal.bias == {} and cal.sigma == {}


def test_apply_corrects_weeklykpi():
    cal = Calibration(bias={"total_hvac_energy_kwh": 3.0, "inlet_temp_max_c": 1.0, "pue_mean": 0.05},
                      sigma={"inlet_temp_max_c": 0.5}, n_weeks=2, version="weeks-2")
    corrected = cal.apply(_kpi(energy=100.0, pue=1.2, inlet=24.0))
    assert corrected.total_hvac_energy_kwh == 103.0
    assert corrected.inlet_temp_max == 25.0     # inlet_temp_max_c bias maps to inlet_temp_max
    assert corrected.pue_mean == 1.25
    assert cal.sigma_for("inlet_temp_max_c") == 0.5
    assert CALIB_KEYS == ("total_hvac_energy_kwh", "pue_mean", "inlet_temp_max_c")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_calibrator.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.calibrator'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/planner/calibrator.py
"""Output-residual calibration: learn per-KPI bias + uncertainty from the deploy
loop's paired (predicted, realized) history, and correct twin predictions toward
the (perturbed) plant. P2a — the residual stage; P2b consumes sigma for robustness."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from planner.types import WeeklyKPI

# KPI keys shared by predicted_kpis (recommendation.py) and realized_kpis (deploy.py).
CALIB_KEYS = ("total_hvac_energy_kwh", "pue_mean", "inlet_temp_max_c")
# map each history/json KPI key -> the WeeklyKPI attribute it corrects
_KEY_TO_FIELD = {
    "total_hvac_energy_kwh": "total_hvac_energy_kwh",
    "pue_mean": "pue_mean",
    "inlet_temp_max_c": "inlet_temp_max",   # note: WeeklyKPI uses inlet_temp_max (no _c)
}


@dataclass(frozen=True)
class Calibration:
    bias: dict           # key (e.g. "inlet_temp_max_c") -> mean(realized - predicted)
    sigma: dict          # key -> std of residuals
    n_weeks: int
    version: str

    @staticmethod
    def identity() -> "Calibration":
        return Calibration(bias={}, sigma={}, n_weeks=0, version="weeks-0")

    def apply(self, kpi: WeeklyKPI) -> WeeklyKPI:
        """Return a bias-corrected copy of the twin's predicted KPI."""
        updates = {}
        for key, field in _KEY_TO_FIELD.items():
            b = self.bias.get(key)
            if b:
                updates[field] = getattr(kpi, field) + b
        return dataclasses.replace(kpi, **updates) if updates else kpi

    def sigma_for(self, key: str) -> float:
        return self.sigma.get(key, 0.0)

    def to_dict(self) -> dict:
        return {"bias": self.bias, "sigma": self.sigma,
                "n_weeks": self.n_weeks, "version": self.version}

    @staticmethod
    def from_dict(d: dict) -> "Calibration":
        return Calibration(bias=d.get("bias", {}), sigma=d.get("sigma", {}),
                           n_weeks=int(d.get("n_weeks", 0)),
                           version=d.get("version", f"weeks-{int(d.get('n_weeks', 0))}"))


def fit_calibration(history: list) -> Calibration:
    """Fit per-KPI additive bias + sigma from paired (predicted, realized) weeks."""
    bias, sigma = {}, {}
    for key in CALIB_KEYS:
        res = []
        for e in history:
            p = e.get("predicted", {}).get(key)
            r = e.get("realized", {}).get(key)
            if p is not None and r is not None:
                res.append(r - p)
        if res:
            m = sum(res) / len(res)
            bias[key] = m
            sigma[key] = (sum((x - m) ** 2 for x in res) / len(res)) ** 0.5 if len(res) > 1 else 0.0
    n = len(history)
    return Calibration(bias=bias, sigma=sigma, n_weeks=n, version=f"weeks-{n}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_calibrator.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/calibrator.py src/tests/test_calibrator.py
git commit -m "feat(dtwin): Calibration model + fit_calibration (per-KPI residual bias+sigma)"
```

---

## Task 2: Calibration persistence (`calibrator.py` load/save/recompute)

**Files:** Modify `src/planner/calibrator.py`; Test `src/tests/test_calibrator.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_calibrator.py
import json as _json
from pathlib import Path
from planner.calibrator import load_calibration, save_calibration, recompute_calibration


def test_save_load_roundtrip(tmp_path):
    cal = Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                      n_weeks=2, version="weeks-2")
    p = str(tmp_path / "calibration.json")
    save_calibration(cal, p)
    got = load_calibration(p)
    assert got.bias["inlet_temp_max_c"] == 1.0 and got.n_weeks == 2


def test_load_missing_returns_identity(tmp_path):
    got = load_calibration(str(tmp_path / "nope.json"))
    assert got.n_weeks == 0 and got.bias == {}


def test_recompute_calibration_from_history(tmp_path):
    hist = [{"week_start": "2013-11-11",
             "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
             "realized":  {"total_hvac_energy_kwh": 105.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}}]
    hpath = tmp_path / "calibration_history.json"
    hpath.write_text(_json.dumps(hist))
    out = tmp_path / "calibration.json"
    cal = recompute_calibration(str(hpath), str(out))
    assert cal.bias["total_hvac_energy_kwh"] == 5.0
    assert load_calibration(str(out)).bias["total_hvac_energy_kwh"] == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_calibrator.py -q`
Expected: FAIL with `ImportError: cannot import name 'load_calibration'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/planner/calibrator.py
def load_calibration(path: str = "data/calibration.json") -> Calibration:
    p = Path(path)
    return Calibration.from_dict(json.loads(p.read_text())) if p.exists() else Calibration.identity()


def save_calibration(cal: Calibration, path: str = "data/calibration.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cal.to_dict(), indent=2))


def recompute_calibration(history_path: str = "data/calibration_history.json",
                          out_path: str = "data/calibration.json") -> Calibration:
    """Re-fit the Calibration from the paired history and persist it."""
    hp = Path(history_path)
    hist = json.loads(hp.read_text()) if hp.exists() else []
    cal = fit_calibration(hist)
    save_calibration(cal, out_path)
    return cal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_calibrator.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/calibrator.py src/tests/test_calibrator.py
git commit -m "feat(dtwin): calibration persistence (load/save/recompute calibration.json)"
```

---

## Task 3: Paired history at deploy (`history.py` `advance_calibration`)

**Files:** Modify `src/planner/history.py`; Test `src/tests/test_history.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_history.py
import json as _json
from planner.history import advance_calibration


def test_advance_calibration_pairs_predicted_and_realized(tmp_path):
    path = str(tmp_path / "calibration_history.json")
    predicted = {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    realized = {"total_hvac_energy_kwh": 105.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.5}
    advance_calibration(predicted, realized, date(2013, 11, 11), path)
    hist = _json.loads(open(path).read())
    assert len(hist) == 1
    assert hist[0]["week_start"] == "2013-11-11"
    assert hist[0]["predicted"]["total_hvac_energy_kwh"] == 100.0
    assert hist[0]["realized"]["total_hvac_energy_kwh"] == 105.0


def test_advance_calibration_idempotent_per_week(tmp_path):
    path = str(tmp_path / "calibration_history.json")
    advance_calibration({"a": 1}, {"a": 2}, date(2013, 11, 11), path)
    advance_calibration({"a": 10}, {"a": 20}, date(2013, 11, 11), path)
    hist = _json.loads(open(path).read())
    assert len(hist) == 1 and hist[0]["realized"]["a"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_history.py -q`
Expected: FAIL with `ImportError: cannot import name 'advance_calibration'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/planner/history.py  (json + date already importable; add `import json` at top if absent)
def advance_calibration(predicted: dict, realized: dict, week_start: date,
                        path: str = "data/calibration_history.json") -> None:
    """Append/replace one paired (predicted, realized) KPI record per deployed week.

    This is the SEPARATE paired history the P2 Calibrator fits residuals from — NOT
    the forecaster's per-step CSV. Idempotent per week_start."""
    import json
    from pathlib import Path
    p = Path(path)
    hist = json.loads(p.read_text()) if p.exists() else []
    hist = [e for e in hist if e.get("week_start") != week_start.isoformat()]
    hist.append({"week_start": week_start.isoformat(),
                 "predicted": predicted, "realized": realized})
    hist.sort(key=lambda e: e["week_start"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hist, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_history.py -q`
Expected: PASS (all history tests).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/history.py src/tests/test_history.py
git commit -m "feat(dtwin): advance_calibration — paired (predicted,realized) deploy history"
```

---

## Task 4: Corrected objective in the planner (`beam_search.py` + `pipeline.py`)

**Files:** Modify `src/planner/beam_search.py`, `src/planner/pipeline.py`; Test `src/tests/test_beam_search.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_beam_search.py
from planner.beam_search import BeamPlanner, BeamConfig
from planner.objective import ObjectiveWeights
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.types import DEFAULT_SEARCH_SPACE
from planner.calibrator import Calibration


def test_calibration_bias_shifts_feasibility():
    # A +3 C inlet bias makes the mock's borderline-feasible region infeasible,
    # forcing the planner toward a cooler (lower-inlet) setpoint than uncalibrated.
    ev = MockEvaluator(MockSurface())
    cfg = BeamConfig(grid=3, beam_width=3, levels=1)
    base = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(), cfg).plan()
    cal = Calibration(bias={"inlet_temp_max_c": 3.0}, sigma={}, n_weeks=1, version="weeks-1")
    calibrated = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(), cfg,
                             calibration=cal).plan()
    # corrected run must report a higher (bias-added) peak inlet for its chosen point
    assert calibrated.best_kpi.inlet_temp_max >= base.best_kpi.inlet_temp_max
    # and it must stay feasible (0 violations) under the correction
    assert calibrated.feasible


def test_planner_without_calibration_unchanged():
    ev = MockEvaluator(MockSurface())
    res = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                      BeamConfig(grid=3, beam_width=2, levels=1)).plan()  # no calibration arg
    assert res.feasible
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_beam_search.py -q`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'calibration'`.

- [ ] **Step 3: Write minimal implementation**

In `src/planner/beam_search.py`, add `calibration` to `BeamPlanner.__init__` and apply it in `_score_batch`. Change the constructor (keep the existing body, add the attribute):

```python
    def __init__(self, space, evaluator, weights=None, config=None, calibration=None):
        self.space = space
        self.evaluator = evaluator
        self.weights = weights or ObjectiveWeights()
        self.config = config or BeamConfig()
        self.calibration = calibration
```

And in `_score_batch`, apply the correction to each KPI before scoring:

```python
    def _score_batch(self, candidates, forecast, on_result=None):
        kpis = self.evaluator.evaluate(candidates, forecast, on_result=on_result)
        if self.calibration is not None:
            kpis = [self.calibration.apply(k) for k in kpis]
        return [(c, k, score(k, self.weights)) for c, k in zip(candidates, kpis)]
```

(If `__init__`/`_score_batch` differ slightly from the above in the file, preserve the existing logic and only add the `calibration` attribute + the two-line apply. `score` is already imported in this module.)

In `src/planner/pipeline.py`, thread the calibration through `run_weekly_plan`. Add a parameter and pass it to `BeamPlanner`:

```python
def run_weekly_plan(
    request: PlanRequest,
    evaluator: Evaluator,
    forecaster,
    baseline_energy_kwh: Optional[float] = None,
    weights: Optional[ObjectiveWeights] = None,
    on_level: Optional[Callable[[int, int, float], None]] = None,
    on_eval: Optional[Callable[[int], None]] = None,
    calibration=None,
) -> dict:
```

and change the planner construction (the existing `BeamPlanner(space, evaluator, weights, beam)` line) to:

```python
    planner = BeamPlanner(space, evaluator, weights, beam, calibration=calibration)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_beam_search.py tests/test_pipeline.py -q`
Expected: PASS (new tests + existing beam/pipeline tests still green — `calibration=None` is the default, so existing behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/beam_search.py src/planner/pipeline.py src/tests/test_beam_search.py
git commit -m "feat(dtwin): corrected objective — BeamPlanner applies Calibration before scoring"
```

---

## Task 5: Deploy records paired history + recomputes calibration; plan uses it (`jobs.py`)

**Files:** Modify `src/webapp/jobs.py`; Test `src/tests/test_jobs.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_jobs.py
import json as _json
from pathlib import Path


def test_deploy_writes_paired_history_and_calibration(tmp_path, monkeypatch):
    # run_deploy_job is dctwin-coupled; test the calibration side-effects via a
    # thin stand-in that mirrors its post-deploy steps using the real helpers.
    from planner.history import advance_calibration
    from planner.calibrator import recompute_calibration, load_calibration

    hist = str(tmp_path / "calibration_history.json")
    cal_out = str(tmp_path / "calibration.json")
    predicted = {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    realized = {"total_hvac_energy_kwh": 106.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0}
    from datetime import date
    advance_calibration(predicted, realized, date(2013, 11, 11), hist)
    cal = recompute_calibration(hist, cal_out)
    assert cal.bias["total_hvac_energy_kwh"] == 6.0
    assert load_calibration(cal_out).n_weeks == 1
```

(This locks the post-deploy contract via the real helpers. The wiring in `run_deploy_job` is verified by the integration test in P1's Task 9 conventions; here we assert the helpers compose correctly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py::test_deploy_writes_paired_history_and_calibration -q`
Expected: PASS immediately (it uses the already-built helpers) — if it FAILS, the helpers from Tasks 1–3 are wrong; fix them. (This is a contract test, not TDD-red for new code.)

- [ ] **Step 3: Wire the helpers into the deploy + plan jobs**

In `src/webapp/jobs.py` `run_deploy_job`, after the existing `advance_history(rec["realized_kpis"], week_start, "data/realized_history.csv")` line, add the paired-history + recompute:

```python
    from planner.history import advance_calibration
    from planner.calibrator import recompute_calibration
    advance_calibration(rec["predicted_kpis"], rec["realized_kpis"], week_start,
                        "data/calibration_history.json")
    recompute_calibration("data/calibration_history.json", "data/calibration.json")
```

In `src/webapp/jobs.py` `run_plan_job`, load the calibration and pass it to `run_weekly_plan` so the search is bias-corrected. Add near the other lazy imports:

```python
    from planner.calibrator import load_calibration
```

and add `calibration=load_calibration("data/calibration.json")` to the `run_weekly_plan(...)` call (alongside `on_level=on_level, on_eval=on_eval`).

- [ ] **Step 4: Run tests to verify nothing regressed**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py -q && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "import webapp.jobs"`
Expected: PASS + clean import (the existing job tests inject fake runners, so the real lazy imports are only resolved at import time — confirm `import webapp.jobs` succeeds).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/webapp/jobs.py src/tests/test_jobs.py
git commit -m "feat(dtwin): deploy writes paired history + recomputes calibration; plan uses it"
```

---

## Task 6: `GET /api/calibration` (`main.py`)

**Files:** Modify `src/webapp/main.py`; Test `src/tests/test_api.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_api.py
def test_get_calibration(tmp_path, monkeypatch):
    from webapp.main import create_app
    from webapp.auth import TokenAuth
    from webapp.store import PlanStore
    from fastapi.testclient import TestClient
    from planner.calibrator import Calibration, save_calibration

    monkeypatch.chdir(tmp_path)                       # isolate data/ writes
    save_calibration(Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                                 n_weeks=2, version="weeks-2"), "data/calibration.json")
    store = PlanStore(runs_dir="runs", db_path="index.db")
    app = create_app(store=store, auth=TokenAuth({"op": "operator"}), run_sync=True)
    client = TestClient(app)
    r = client.get("/api/calibration", headers={"Authorization": "Bearer op"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_weeks"] == 2
    assert body["bias"]["inlet_temp_max_c"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_api.py::test_get_calibration -q`
Expected: FAIL (404 — route doesn't exist).

- [ ] **Step 3: Add the route**

In `src/webapp/main.py`, after the `get_topology` route (near the end of `create_app`, before `return app`), add:

```python
    from planner.calibrator import load_calibration

    @app.get("/api/calibration")
    def get_calibration(role: str = Depends(operator)):
        return load_calibration("data/calibration.json").to_dict()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_api.py -q`
Expected: PASS (new test + existing api tests).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/webapp/main.py src/tests/test_api.py
git commit -m "feat(dtwin): GET /api/calibration (current bias/sigma/n_weeks)"
```

---

## Task 7: Frontend — surface calibration (`api.ts` + `Review.tsx`)

**Files:** Modify `src/frontend/src/api.ts`, `src/frontend/src/pages/Review.tsx`, `src/frontend/src/pages/Review.test.tsx`.

- [ ] **Step 1: Write the failing test**

```typescript
// append to src/frontend/src/pages/Review.test.tsx — add getCalibration to the api mock
// (in the existing vi.mock('../api', ...) block add: getCalibration: vi.fn().mockResolvedValue(
//   { bias: { inlet_temp_max_c: 0.8 }, sigma: { inlet_temp_max_c: 0.4 }, n_weeks: 2, version: 'weeks-2' }))
it('shows the twin calibration state', async () => {
  render(<Review planId="plan-1" />);   // match how other Review tests render it
  expect(await screen.findByText(/Twin Calibration/i)).toBeInTheDocument();
  expect(await screen.findByText(/2 weeks/i)).toBeInTheDocument();
});
```

(Match the existing `Review.test.tsx` render signature + api-mock structure exactly; if it renders `<Review onBack=... planId=.../>` or similar, mirror that.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run test -- --run src/pages/Review.test.tsx 2>&1 | tail -8`
Expected: FAIL (no "Twin Calibration" text / `getCalibration` undefined).

- [ ] **Step 3: Implement**

In `src/frontend/src/api.ts` add the type + client:

```typescript
export interface CalibrationState {
  bias: Record<string, number>;
  sigma: Record<string, number>;
  n_weeks: number;
  version: string;
}
export const getCalibration = () => req<CalibrationState>(`/api/calibration`);
```

In `src/frontend/src/pages/Review.tsx`: load calibration on mount (mirror the existing `getPlan` effect pattern) into state `cal`, and render a small **Twin Calibration** card (reuse the existing `bracket-card`/metric styling) showing `n_weeks` (e.g. `{cal.n_weeks} weeks`), and when `cal.n_weeks > 0` the inlet bias/σ (`cal.bias.inlet_temp_max_c` °C, `cal.sigma.inlet_temp_max_c` °C) and energy bias (`cal.bias.total_hvac_energy_kwh` kWh). Guard against missing fields (show `—`). Render the card near the KPI comparison section. Degrade gracefully if `getCalibration()` rejects (hide the card).

- [ ] **Step 4: Run build + tests**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: build clean; all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/frontend/src/api.ts src/frontend/src/pages/Review.tsx src/frontend/src/pages/Review.test.tsx
git commit -m "feat(dtwin): web Twin Calibration panel (bias/sigma/n_weeks)"
```

---

## Task 8: Full-suite verification + spec note

**Files:** none (verification) + optional `docs` note.

- [ ] **Step 1: Run the whole backend suite**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q 2>&1 | tail -3`
Expected: all pass (prior 128 + the new calibrator/history/beam/jobs/api tests), 4 deselected (integration).

- [ ] **Step 2: Run the frontend suite**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: build clean; all pass.

- [ ] **Step 3: Sanity-check the corrected loop end-to-end (no Docker)**

Run a quick check that a fitted calibration changes a planned recommendation's predicted KPI under the mock:
```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "
from planner.calibrator import Calibration
from planner.beam_search import BeamPlanner, BeamConfig
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.types import DEFAULT_SEARCH_SPACE
from planner.objective import ObjectiveWeights
cal = Calibration(bias={'total_hvac_energy_kwh': 50.0}, sigma={}, n_weeks=1, version='weeks-1')
r = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface()), ObjectiveWeights(), BeamConfig(grid=3,beam_width=2,levels=1), calibration=cal).plan()
print('corrected best energy includes +50 bias:', r.best_kpi.total_hvac_energy_kwh)
"
```
Expected: prints a corrected energy that includes the +50 bias.

- [ ] **Step 4: Commit (if any doc note added)**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add -A && git commit -m "test(dtwin): P2a full-suite verification green" --allow-empty
```

---

## Self-review notes

- **Spec coverage (P2a / spec §5.3, §6.1, §6.2, §7 calibration.json, §9 M4–M5):** Calibration model + fit (Task 1) ✓; persistence calibration.json (Task 2) ✓; paired deploy history (Task 3) ✓; corrected objective wired into the search (Task 4) ✓; deploy recompute + plan-uses-calibration (Task 5) ✓; `GET /api/calibration` (Task 6) ✓; UI surfacing (Task 7) ✓.
- **Deferred to P2b/P2c (out of scope here):** scenario/ensemble generation (`make_scenarios`), `robust_rerank` (worst-case feasibility + CVaR), `PlanResult.beam_finalists` exposure, recommendation schema 1.1 `robust` block + confidence bands, `Recalibrator` seam, the inner-search k·σ pre-tighten. These are the follow-up plan.
- **Type consistency:** `Calibration` (bias/sigma/n_weeks/version) is used identically in Tasks 1,2,4,5,6,7; `CALIB_KEYS`/`_KEY_TO_FIELD` map the `inlet_temp_max_c` ↔ `inlet_temp_max` mismatch in one place (Task 1); `load_calibration("data/calibration.json")` path is consistent across jobs (Task 5) and the API (Task 6); `advance_calibration` history path `data/calibration_history.json` matches between Task 3, Task 5, and `recompute_calibration`'s default.
- **Backward compatibility:** every new param defaults to identity/None — no calibration file → `Calibration.identity()` → unchanged planning (week 1 behaves as today). Existing tests stay green.
