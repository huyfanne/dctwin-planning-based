# Fidelity Loop P2b — Scenario/Ensemble-Robust Selection (+ P2c seam) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-rank the beam's top-K finalists across an ensemble of perturbed-plant scenarios (drawn around `DEFAULT_PLANT`, widened by the calibrated σ) and pick the robust winner — worst-case inlet feasibility (≤ 26 °C in *every* scenario) + CVaR_α energy — attaching confidence bands to the recommendation; plus the P2c recalibrator seam.

**Architecture:** Additive on P2a. `BeamPlanner.plan()` now exposes the final beam (`PlanResult.beam_finalists`). A new pure `planner/robust.py` provides `make_scenarios` (deterministic PlantConfig draws), `scenario_spread` (σ→ensemble width), and `robust_select` (worst-case feasibility + CVaR + bands) — all unit-testable with synthetic KPIs. A `make_oracle_robust_rerank` closure does the EnergyPlus-coupled orchestration (build N scenario prototxts + oracles, evaluate the finalists), injected into `run_weekly_plan` via an optional `robust_rerank_fn` so the pipeline stays MockEvaluator-testable. `build_recommendation` gains a `robust` block (schema 1.1); the web Review page shows confidence bands. This is P2b+P2c of `docs/superpowers/specs/2026-06-06-closing-fidelity-loop-design.md`.

**Tech Stack:** Python 3.13, dctwin/EnergyPlus 9.5 (opyplus, BCVTB/Docker), FastAPI, React/TS, pytest/vitest. Backend tests from `src/`: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest`. Frontend from `src/frontend`: `npm run build && npm run test -- --run`.

---

## Grounding facts (verified against the post-P2a-merge code)

- **`PlanResult`** (`planner/beam_search.py:24-31`, `@dataclass`, NOT frozen): `best, best_kpi, best_score, evals, feasible, history`. No `beam_finalists` yet. Imports `from dataclasses import dataclass` (need to add `field`).
- **`plan()` return** (`beam_search.py` ~line 128-131): `best_s, best_kpi, best_sc = beam[0]; feasible = best_sc != INFEASIBLE; return PlanResult(best_s, best_kpi, best_sc, evals, feasible, history)`. `beam` is `list[_Scored]`, sorted ascending by score (beam[0]=best). `_Scored = tuple[Setpoints, WeeklyKPI, float]` (`beam_search.py:34-35`). Calibration is already applied in `_score_batch`, so beam KPIs are calibrated.
- **`run_weekly_plan`** (`planner/pipeline.py:23-61`): `def run_weekly_plan(request, evaluator, forecaster, baseline_energy_kwh=None, weights=None, on_level=None, on_eval=None, calibration=None)`. Body: `forecast = forecaster.forecast(...)`; `planner = BeamPlanner(space, evaluator, weights, beam, calibration=calibration)`; `result = planner.plan(forecast, on_level=on_level, on_eval=on_eval)`; then feasible/fallback; then `build_recommendation(setpoints=best, kpi=kpi, week_start=request.week_start, days=request.days, forecast_method=..., search_meta={...}, baseline_energy_kwh=..., status=status)`.
- **`build_recommendation`** (`planner/recommendation.py:25-62`): params `(setpoints, kpi, week_start, days, forecast_method, search_meta, baseline_energy_kwh=None, status="pending_approval")`; returns a dict with `schema_version="1.0"`, …, `predicted_kpis` (keys `total_hvac_energy_kwh, pue_mean, inlet_temp_max_c, inlet_violation_steps, energy_reduction_vs_baseline_pct`), `forecast`, `search`, `status`.
- **`objective`** (`objective.py`): `is_feasible(kpi, w) -> bool` (False if `not kpi.feasible` or `inlet_violation_steps > w.inlet_tol_steps` or rh-hard); `INFEASIBLE = math.inf`.
- **`Calibration`** (`planner/calibrator.py`): frozen; `sigma_for(key) -> float`; keys are `total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max_c`; `n_weeks`, `version`.
- **`plant.py`**: `Perturbation(table, field, factor)` (frozen); `PlantConfig(perturbations: tuple[Perturbation,...])` (frozen); `DEFAULT_PLANT = PlantConfig((Perturbation("Fan_VariableVolume","fan_total_efficiency",0.93), Perturbation("Coil_Cooling_Water","design_water_flow_rate",0.85)))`; `build_plant_prototxt(base_prototxt, plant, out_dir) -> str` (writes perturbed IDF + prototxt).
- **`oracle.py`**: `ParallelEnvOracle(base_prototxt, config=None, project_root=".", worker_fn=None)`; `evaluate(candidates, forecast=None, on_result=None) -> list[WeeklyKPI]`. `OracleConfig(n_workers=8, timeout_s=1800.0, timesteps_per_hour=4, log_root="log/oracle", use_process_pool=True, settings=..., bcvtb_host=..., monitored_hall=...)`.
- **`WeeklyKPI`** (`types.py:48-62`): `total_hvac_energy_kwh, pue_mean, inlet_temp_max, inlet_violation_steps, rh_violation_steps, feasible, inlet_excess_degc_steps, ...`. (Note: `inlet_temp_max` — no `_c`.)
- **`jobs.py` `run_plan_job`**: builds `oracle = ParallelEnvOracle(base_prototxt=dt_cfg, ...)` with `dt_cfg = params.get("dt", "configs/dt/dt.prototxt")`, loads `calibration = load_calibration("data/calibration.json")`, calls `run_weekly_plan(..., calibration=calibration)`.
- **Frontend** (`api.ts`): `interface Recommendation { status: string; setpoints: Record<string, number>; predicted_kpis: Record<string, number | null>; }`. `Review.tsx`: KPI Comparison card ends ~line 329; `rec = detail?.recommendation` ~line 173. `get_plan` route needs NO change (robust flows in recommendation.json).

## File Structure

- **Modify** `src/planner/beam_search.py` — `PlanResult.beam_finalists` + `plan()` returns the beam.
- **Modify** `src/tests/test_beam_search.py` — finalists-exposed test.
- **Create** `src/planner/robust.py` — `make_scenarios`, `scenario_spread`, `RobustResult`, `robust_select`, `make_oracle_robust_rerank`.
- **Create** `src/tests/test_robust.py`.
- **Modify** `src/planner/pipeline.py` — `run_weekly_plan(..., robust_rerank_fn=None)` applies it; builds the robust block.
- **Modify** `src/tests/test_pipeline.py` — robust-rerank wiring test (mock fn).
- **Modify** `src/planner/recommendation.py` — `build_recommendation` robust block + schema 1.1.
- **Modify** `src/tests/test_recommendation.py` — robust block test.
- **Modify** `src/webapp/jobs.py` — `run_plan_job` builds + passes the production `robust_rerank_fn`.
- **Modify** `src/tests/test_jobs.py` — closure-contract test.
- **Modify** `src/frontend/src/api.ts` + `src/frontend/src/pages/Review.tsx` (+ test) — `robust` interface + Confidence Bands card.
- **Create** `src/planner/recalibrator.py` (+ test) — P2c seam stub.
- **Create** `src/tests/integration/test_robust_rerank.py` — marked Docker integration.

---

## Task 1: Expose beam finalists (`beam_search.py`)

**Files:** Modify `src/planner/beam_search.py`; Test `src/tests/test_beam_search.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_beam_search.py
def test_plan_exposes_beam_finalists():
    ev = MockEvaluator(MockSurface())
    cfg = BeamConfig(grid=3, beam_width=4, levels=1)
    res = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(), cfg).plan()
    assert hasattr(res, "beam_finalists")
    assert 1 <= len(res.beam_finalists) <= 4              # up to beam_width
    s0, k0, sc0 = res.beam_finalists[0]                   # _Scored tuple shape
    assert (s0, k0, sc0) == (res.best, res.best_kpi, res.best_score)   # beam[0] is the best
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_beam_search.py::test_plan_exposes_beam_finalists -q`
Expected: FAIL with `AttributeError: 'PlanResult' object has no attribute 'beam_finalists'`.

- [ ] **Step 3: Implement**

In `src/planner/beam_search.py`: (a) change the import `from dataclasses import dataclass` to `from dataclasses import dataclass, field`; (b) add the field to `PlanResult` (after `history`):
```python
    history: list[float]     # best score after each level
    beam_finalists: list = field(default_factory=list)   # final beam: list[_Scored]
```
(c) change the `plan()` return to include the beam:
```python
        best_s, best_kpi, best_sc = beam[0]
        feasible = best_sc != INFEASIBLE
        return PlanResult(best_s, best_kpi, best_sc, evals, feasible, history,
                          beam_finalists=list(beam))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_beam_search.py -q`
Expected: PASS (new test + all existing beam tests — the field has a default, so existing `PlanResult(...)` construction is unaffected).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/beam_search.py src/tests/test_beam_search.py
git commit -m "feat(dtwin): expose beam finalists on PlanResult for robust re-rank"
```

---

## Task 2: Scenario generation (`robust.py` — `make_scenarios` + `scenario_spread`)

**Files:** Create `src/planner/robust.py`; Test `src/tests/test_robust.py`.

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_robust.py
import math
from planner.robust import make_scenarios, scenario_spread
from planner.plant import DEFAULT_PLANT
from planner.calibrator import Calibration


def test_make_scenarios_deterministic_spread():
    scs = make_scenarios(DEFAULT_PLANT, n=3, spread=0.1)
    assert len(scs) == 3
    # middle scenario == base; ends scaled by 0.9 and 1.1
    base_fan = DEFAULT_PLANT.perturbations[0].factor
    assert math.isclose(scs[0].perturbations[0].factor, base_fan * 0.9)
    assert math.isclose(scs[1].perturbations[0].factor, base_fan * 1.0)
    assert math.isclose(scs[2].perturbations[0].factor, base_fan * 1.1)


def test_make_scenarios_n1_is_base():
    scs = make_scenarios(DEFAULT_PLANT, n=1, spread=0.1)
    assert len(scs) == 1 and scs[0] == DEFAULT_PLANT


def test_scenario_spread_cold_start_and_widens():
    assert scenario_spread(None) == 0.1                       # cold-start prior
    assert scenario_spread(Calibration({}, {}, 0, "weeks-0")) == 0.1
    wide = scenario_spread(Calibration({}, {"inlet_temp_max_c": 1.0}, 3, "weeks-3"),
                           base_spread=0.1, sigma_ref=1.0)
    assert wide == 0.2                                        # 0.1 * (1 + 1.0/1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.robust'`.

- [ ] **Step 3: Implement (create `src/planner/robust.py`)**

```python
"""Scenario/ensemble-robust setpoint selection (P2b): evaluate the beam finalists
across an ensemble of perturbed-plant scenarios and pick the robust winner —
worst-case inlet feasibility + CVaR energy — with confidence bands."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from planner.calibrator import Calibration
from planner.objective import ObjectiveWeights, is_feasible
from planner.plant import DEFAULT_PLANT, Perturbation, PlantConfig
from planner.types import Setpoints, WeeklyKPI

# robust KPI keys (json/band keys) -> WeeklyKPI attribute
ROBUST_KEYS = ("total_hvac_energy_kwh", "inlet_temp_max_c", "pue_mean")
_RKEY_FIELD = {
    "total_hvac_energy_kwh": "total_hvac_energy_kwh",
    "inlet_temp_max_c": "inlet_temp_max",
    "pue_mean": "pue_mean",
}


def make_scenarios(base: PlantConfig, n: int, spread: float) -> list[PlantConfig]:
    """N deterministic PlantConfig draws: scale EVERY perturbation factor by
    evenly-spaced multipliers in [1-spread, 1+spread]. n<=1 -> [base]."""
    if n <= 1:
        return [base]
    out = []
    for i in range(n):
        m = (1.0 - spread) + (2.0 * spread) * i / (n - 1)
        out.append(PlantConfig(tuple(
            Perturbation(p.table, p.field, p.factor * m) for p in base.perturbations)))
    return out


def scenario_spread(calibration: Optional[Calibration], base_spread: float = 0.1,
                    sigma_ref: float = 1.0) -> float:
    """Ensemble half-width: a prior at cold-start, widened by the calibrated inlet
    uncertainty so the ensemble brackets the observed mismatch."""
    if calibration is None or calibration.n_weeks == 0:
        return base_spread
    return base_spread * (1.0 + calibration.sigma_for("inlet_temp_max_c") / sigma_ref)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/robust.py src/tests/test_robust.py
git commit -m "feat(dtwin): robust scenario generation (make_scenarios + sigma-scaled spread)"
```

---

## Task 3: Robust selection (`robust.py` — `RobustResult` + `robust_select`)

**Files:** Modify `src/planner/robust.py`; Test `src/tests/test_robust.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_robust.py
from planner.robust import RobustResult, robust_select
from planner.objective import ObjectiveWeights
from planner.types import Setpoints, WeeklyKPI


def _kpi(energy, inlet, viol=0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True,
                     inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)


def test_robust_select_prefers_robust_feasible_then_cvar():
    sp_a, sp_b = Setpoints(24, 8, 17), Setpoints(22, 10, 15)
    finalists = [(sp_a, _kpi(100, 24), 100.0), (sp_b, _kpi(110, 23), 110.0)]
    # A is cheaper nominally but VIOLATES in one scenario; B is feasible in all
    scenario_kpis = [
        [_kpi(100, 24), _kpi(105, 27, viol=3)],   # finalist A: scenario 2 breaches cap
        [_kpi(110, 23), _kpi(112, 25)],           # finalist B: feasible everywhere
    ]
    rr = robust_select(finalists, scenario_kpis, ObjectiveWeights())
    assert rr.winner == sp_b                       # A excluded (not robust-feasible)
    assert rr.robust_feasible is True
    assert rr.n_scenarios == 2
    assert rr.confidence_bands["inlet_temp_max_c"]["max"] == 25.0
    assert rr.cvar_energy_kwh == 112.0             # worst-tail energy of B


def test_robust_select_all_infeasible_returns_least_bad():
    sp = Setpoints(24, 8, 17)
    finalists = [(sp, _kpi(100, 24), 100.0)]
    scenario_kpis = [[_kpi(100, 28, viol=5)]]      # violates in the only scenario
    rr = robust_select(finalists, scenario_kpis, ObjectiveWeights())
    assert rr.winner == sp and rr.robust_feasible is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: FAIL with `ImportError: cannot import name 'robust_select'`.

- [ ] **Step 3: Implement (append to `src/planner/robust.py`)**

```python
@dataclass
class RobustResult:
    winner: Setpoints
    winner_kpi: WeeklyKPI            # the calibrated NOMINAL kpi (twin's best estimate)
    robust_feasible: bool            # feasible in EVERY scenario
    cvar_energy_kwh: float           # CVaR_alpha of energy across scenarios
    confidence_bands: dict           # {kpi_key: {"p50","p90","max"}}
    n_scenarios: int


def _cvar(values: list, alpha: float) -> float:
    """Mean of the worst (1-alpha) upper tail (higher energy = worse)."""
    if not values:
        return math.inf
    k = max(1, math.ceil((1.0 - alpha) * len(values)))
    return sum(sorted(values, reverse=True)[:k]) / k


def _quantile(values: list, q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def robust_select(finalists: list, scenario_kpis: list,
                  weights: ObjectiveWeights, alpha: float = 0.8) -> RobustResult:
    """finalists: list of (Setpoints, WeeklyKPI, score). scenario_kpis[i]: the list
    of per-scenario WeeklyKPI for finalist i. Worst-case inlet feasibility (feasible
    in EVERY scenario) + CVaR_alpha energy; ties broken by lowest CVaR energy."""
    n_scen = len(scenario_kpis[0]) if scenario_kpis else 0
    robust_feasible = [
        bool(ks) and all(is_feasible(k, weights) for k in ks) for ks in scenario_kpis
    ]
    pool = [i for i, ok in enumerate(robust_feasible) if ok] or list(range(len(finalists)))

    def cvar_e(i):
        return _cvar([k.total_hvac_energy_kwh for k in scenario_kpis[i]], alpha)

    win = min(pool, key=cvar_e)
    bands = {}
    for key in ROBUST_KEYS:
        vals = [getattr(k, _RKEY_FIELD[key]) for k in scenario_kpis[win]]
        bands[key] = {"p50": _quantile(vals, 0.5), "p90": _quantile(vals, 0.9), "max": max(vals)}
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=n_scen)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/robust.py src/tests/test_robust.py
git commit -m "feat(dtwin): robust_select — worst-case feasibility + CVaR energy + bands"
```

---

## Task 4: Scenario orchestration (`robust.py` — `make_oracle_robust_rerank`)

**Files:** Modify `src/planner/robust.py`; Test `src/tests/test_robust.py`.

- [ ] **Step 1: Write the failing test (inject a fake oracle — no EnergyPlus)**

```python
# append to src/tests/test_robust.py
from planner.robust import make_oracle_robust_rerank


class _FakeOracle:
    """Records the scenario prototxt it was built on; returns inlet that rises
    with the scenario's perturbation severity so worst-case feasibility bites."""
    instances = []

    def __init__(self, base_prototxt, config=None, project_root="."):
        self.base_prototxt = base_prototxt
        _FakeOracle.instances.append(base_prototxt)

    def evaluate(self, candidates, forecast=None, on_result=None):
        return [_kpi(100.0, 24.0) for _ in candidates]


class _FakeOracleCfg:
    n_workers = 1
    timesteps_per_hour = 4


def test_make_oracle_robust_rerank_runs_scenarios(tmp_path, monkeypatch):
    # avoid real dctwin prototxt I/O: stub build_plant_prototxt to a path string
    import planner.robust as R
    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")
    _FakeOracle.instances = []
    sp = Setpoints(24, 8, 17)
    finalists = [(sp, _kpi(100, 24), 100.0)]
    fn = make_oracle_robust_rerank(
        base_prototxt="configs/dt/dt.prototxt", oracle_config=_FakeOracleCfg(),
        calibration=None, weights=ObjectiveWeights(), n_scenarios=3,
        log_root=str(tmp_path), oracle_cls=_FakeOracle)
    rr = fn(finalists, forecast=None)
    assert rr.n_scenarios == 3
    assert len(_FakeOracle.instances) == 3          # one oracle per scenario
    assert rr.winner == sp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py::test_make_oracle_robust_rerank_runs_scenarios -q`
Expected: FAIL with `ImportError: cannot import name 'make_oracle_robust_rerank'`.

- [ ] **Step 3: Implement (append to `src/planner/robust.py`)**

Add a module-level import near the top so the test's `monkeypatch.setattr(R, "build_plant_prototxt", ...)` works:
```python
from planner.plant import build_plant_prototxt
```
Then append:
```python
def make_oracle_robust_rerank(base_prototxt, oracle_config, calibration,
                              weights, n_scenarios, log_root, oracle_cls=None):
    """Build a robust_rerank_fn(finalists, forecast) -> RobustResult that evaluates
    the finalists under N perturbed-plant scenarios (each a real EnergyPlus run).
    `oracle_cls` is injectable for testing (default ParallelEnvOracle)."""
    from pathlib import Path

    if oracle_cls is None:
        from planner.oracle import ParallelEnvOracle
        oracle_cls = ParallelEnvOracle

    spread = scenario_spread(calibration)
    scenarios = make_scenarios(DEFAULT_PLANT, n_scenarios, spread)

    def rerank(finalists, forecast):
        from planner.oracle import OracleConfig
        setpoints = [f[0] for f in finalists]
        per_finalist = [[] for _ in finalists]
        for j, sc in enumerate(scenarios):
            sdir = str(Path(log_root) / f"scenario-{j:02d}")
            sproto = build_plant_prototxt(base_prototxt, sc, sdir)
            oracle = oracle_cls(
                base_prototxt=sproto, project_root=".",
                config=OracleConfig(n_workers=oracle_config.n_workers,
                                    timesteps_per_hour=oracle_config.timesteps_per_hour,
                                    log_root=str(Path(sdir) / "oracle")))
            for i, k in enumerate(oracle.evaluate(setpoints, forecast=forecast)):
                per_finalist[i].append(k)
        return robust_select(finalists, per_finalist, weights)

    return rerank
```
(The test injects `_FakeOracleCfg` for `oracle_config`; `OracleConfig` is imported lazily inside `rerank` so the fake oracle path doesn't require it at import time — but it IS imported when `rerank` runs, so ensure `planner.oracle.OracleConfig` exists, which it does.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_robust.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/robust.py src/tests/test_robust.py
git commit -m "feat(dtwin): make_oracle_robust_rerank — N scenario oracles over finalists"
```

---

## Task 5: Wire robust re-rank into `run_weekly_plan` (`pipeline.py`)

**Files:** Modify `src/planner/pipeline.py`; Test `src/tests/test_pipeline.py`.

- [ ] **Step 1: Write the failing test (inject a mock rerank fn — no EnergyPlus)**

```python
# append to src/tests/test_pipeline.py
from planner.robust import RobustResult
from planner.types import Setpoints, WeeklyKPI


def test_run_weekly_plan_applies_robust_rerank(make_request_and_mocks):
    # `make_request_and_mocks` — reuse the existing fixture/helpers in this file
    # that build a PlanRequest + MockEvaluator + a simple forecaster. If none
    # exists, construct them inline as the other tests in this file do.
    request, evaluator, forecaster = make_request_and_mocks
    chosen = Setpoints(21.0, 12.0, 14.0)
    chosen_kpi = WeeklyKPI(total_hvac_energy_kwh=999.0, pue_mean=1.1, inlet_temp_max=25.0,
                           inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                           inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)

    def fake_rerank(finalists, forecast):
        return RobustResult(winner=chosen, winner_kpi=chosen_kpi, robust_feasible=True,
                            cvar_energy_kwh=1010.0,
                            confidence_bands={"inlet_temp_max_c": {"p50": 25.0, "p90": 25.5, "max": 26.0}},
                            n_scenarios=3)

    rec = run_weekly_plan(request, evaluator, forecaster, robust_rerank_fn=fake_rerank)
    # robust winner replaces beam[0] in the recommendation
    assert rec["setpoints"]["crah_supply_air_temperature_c"] == 21.0
    assert rec["robust"]["robust_feasible"] is True
    assert rec["robust"]["cvar_energy_kwh"] == 1010.0
    assert rec["schema_version"] == "1.1"


def test_run_weekly_plan_without_robust_unchanged(make_request_and_mocks):
    request, evaluator, forecaster = make_request_and_mocks
    rec = run_weekly_plan(request, evaluator, forecaster)        # no robust_rerank_fn
    assert "robust" not in rec and rec["schema_version"] == "1.0"
```
NOTE: match the EXISTING test_pipeline.py construction of `request`/`evaluator`/`forecaster` (it already builds these for the current pipeline tests — copy that exact setup instead of the `make_request_and_mocks` placeholder; the placeholder name is illustrative).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_pipeline.py -q`
Expected: FAIL (`run_weekly_plan() got an unexpected keyword argument 'robust_rerank_fn'`).

- [ ] **Step 3: Implement**

In `src/planner/pipeline.py`: add `robust_rerank_fn=None` to the signature (after `calibration=None`). After `result = planner.plan(...)` and BEFORE the `if result.feasible:` block, insert:
```python
    robust = None
    if robust_rerank_fn is not None and result.beam_finalists:
        robust = robust_rerank_fn(result.beam_finalists, forecast)
        result.best, result.best_kpi = robust.winner, robust.winner_kpi
```
(`result.best`/`best_kpi` are mutable — `PlanResult` is not frozen. The robust winner is taken from the beam, which is nominally feasible, so the existing `if result.feasible:` status logic still holds; `robust.robust_feasible` is a separate flag surfaced in the recommendation.)

Then pass the robust fields to `build_recommendation` (add these kwargs to the existing call):
```python
        robust_feasible=(robust.robust_feasible if robust else None),
        cvar_energy_kwh=(robust.cvar_energy_kwh if robust else None),
        confidence_bands=(robust.confidence_bands if robust else None),
        n_scenarios=(robust.n_scenarios if robust else None),
        calibration_version=(calibration.version if calibration is not None else None),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_pipeline.py -q`
Expected: PASS — but Task 6 must land for `build_recommendation` to accept the new kwargs. If Step 4 errors with `build_recommendation() got an unexpected keyword argument`, do Task 6 first, then re-run. (Recommended: implement Task 6 immediately after Task 5 Step 3, before running.)

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/pipeline.py src/tests/test_pipeline.py
git commit -m "feat(dtwin): run_weekly_plan applies robust re-rank to finalists"
```

---

## Task 6: Recommendation schema 1.1 robust block (`recommendation.py`)

**Files:** Modify `src/planner/recommendation.py`; Test `src/tests/test_recommendation.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_recommendation.py
from datetime import date
from planner.recommendation import build_recommendation
from planner.types import Setpoints, WeeklyKPI


def _rk():
    return WeeklyKPI(total_hvac_energy_kwh=80.0, pue_mean=1.2, inlet_temp_max=24.0,
                     inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
                     inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)


def test_recommendation_robust_block_and_schema_11():
    rec = build_recommendation(
        setpoints=Setpoints(24, 8, 17), kpi=_rk(), week_start=date(2013, 11, 11),
        days=7, forecast_method="persistence", search_meta={"evals": 10},
        robust_feasible=True, cvar_energy_kwh=85.0,
        confidence_bands={"inlet_temp_max_c": {"p50": 24.0, "p90": 25.0, "max": 25.5}},
        n_scenarios=4, calibration_version="weeks-3")
    assert rec["schema_version"] == "1.1"
    assert rec["robust"]["robust_feasible"] is True
    assert rec["robust"]["cvar_energy_kwh"] == 85.0
    assert rec["robust"]["confidence_bands"]["inlet_temp_max_c"]["max"] == 25.5
    assert rec["robust"]["n_scenarios"] == 4
    assert rec["robust"]["calibration_version"] == "weeks-3"


def test_recommendation_no_robust_stays_schema_10():
    rec = build_recommendation(setpoints=Setpoints(24, 8, 17), kpi=_rk(),
                               week_start=date(2013, 11, 11), days=7,
                               forecast_method="persistence", search_meta={"evals": 10})
    assert rec["schema_version"] == "1.0" and "robust" not in rec
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recommendation.py::test_recommendation_robust_block_and_schema_11 -q`
Expected: FAIL (`build_recommendation() got an unexpected keyword argument 'robust_feasible'`).

- [ ] **Step 3: Implement**

In `src/planner/recommendation.py`, extend the `build_recommendation` signature (after `status="pending_approval"`):
```python
    robust_feasible: Optional[bool] = None,
    cvar_energy_kwh: Optional[float] = None,
    confidence_bands: Optional[dict] = None,
    n_scenarios: Optional[int] = None,
    calibration_version: Optional[str] = None,
```
Build the dict as today, then before `return`, conditionally add the robust block + bump the version:
```python
    rec = {
        "schema_version": "1.0",
        ... (all existing keys unchanged) ...
        "status": status,
    }
    if robust_feasible is not None:
        rec["schema_version"] = "1.1"
        rec["robust"] = {
            "robust_feasible": robust_feasible,
            "cvar_energy_kwh": cvar_energy_kwh,
            "confidence_bands": confidence_bands or {},
            "n_scenarios": n_scenarios,
            "calibration_version": calibration_version,
        }
    return rec
```
(i.e., replace the bare `return {...}` with assigning to `rec` then the conditional block + `return rec`. `Optional` is already imported in this module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recommendation.py tests/test_pipeline.py -q`
Expected: PASS (recommendation tests + the Task-5 pipeline tests now resolve).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/recommendation.py src/tests/test_recommendation.py
git commit -m "feat(dtwin): recommendation schema 1.1 robust block (feasible/cvar/bands)"
```

---

## Task 7: Production wiring — `run_plan_job` builds the robust re-rank (`jobs.py`)

**Files:** Modify `src/webapp/jobs.py`; Test `src/tests/test_jobs.py`.

- [ ] **Step 1: Write the failing test (contract: the production fn composes)**

```python
# append to src/tests/test_jobs.py
def test_robust_rerank_fn_composes(tmp_path, monkeypatch):
    import planner.robust as R
    from planner.robust import make_oracle_robust_rerank, RobustResult
    from planner.types import Setpoints, WeeklyKPI
    from planner.objective import ObjectiveWeights

    monkeypatch.setattr(R, "build_plant_prototxt",
                        lambda base, plant, out_dir: f"{out_dir}/plant.prototxt")

    class _Cfg:
        n_workers = 1
        timesteps_per_hour = 4

    class _Oracle:
        def __init__(self, base_prototxt, config=None, project_root="."):
            pass
        def evaluate(self, candidates, forecast=None, on_result=None):
            return [WeeklyKPI(100.0, 1.2, 24.0, 0, 0, True, 0.0, 0.0, 0.0) for _ in candidates]

    sp = Setpoints(24, 8, 17)
    fin = [(sp, WeeklyKPI(100.0, 1.2, 24.0, 0, 0, True, 0.0, 0.0, 0.0), 100.0)]
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt", _Cfg(), None,
                                   ObjectiveWeights(), 2, str(tmp_path), oracle_cls=_Oracle)
    rr = fn(fin, forecast=None)
    assert isinstance(rr, RobustResult) and rr.n_scenarios == 2
```
(Verify `WeeklyKPI(100.0, 1.2, 24.0, 0, 0, True, 0.0, 0.0, 0.0)` positional order matches `types.py` — adjust to keyword args if the field order differs.)

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py::test_robust_rerank_fn_composes -q`
Expected: PASS (uses Task 4's function). If it FAILS, Task 4 is wrong — fix it.

- [ ] **Step 3: Wire it into `run_plan_job`**

In `src/webapp/jobs.py` `run_plan_job`, add to the lazy-import block:
```python
    from planner.robust import make_oracle_robust_rerank
```
Build the rerank fn from the plant base prototxt + the oracle's config + the loaded calibration, and pass it to `run_weekly_plan`. After the `oracle = ParallelEnvOracle(...)` construction and the `calibration = load_calibration(...)` line, add:
```python
    robust_rerank_fn = make_oracle_robust_rerank(
        base_prototxt=dt_cfg,
        oracle_config=oracle.config,
        calibration=calibration,
        weights=ObjectiveWeights(),         # must match run_weekly_plan's default weights
        n_scenarios=int(params.get("n_scenarios", 4)),
        log_root=str(plan_dir / "robust"),
    )
```
Then add `robust_rerank_fn=robust_rerank_fn` to the `run_weekly_plan(...)` call (alongside `calibration=...`).

IMPORTANT: the rerank fn closes over its OWN `weights`, which must match what `run_weekly_plan` uses internally (`weights = weights or ObjectiveWeights()` for the BeamPlanner). So pass `ObjectiveWeights()` explicitly: add `from planner.objective import ObjectiveWeights` to `run_plan_job`'s lazy-import block and use `weights=ObjectiveWeights()` in the `make_oracle_robust_rerank(...)` call above (instead of `weights=None`).

- [ ] **Step 4: Verify**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py -q && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -c "import webapp.jobs"`
Expected: all jobs tests pass + clean import.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/webapp/jobs.py src/tests/test_jobs.py
git commit -m "feat(dtwin): run_plan_job builds the production robust re-rank fn"
```

---

## Task 8: Frontend — confidence bands (`api.ts` + `Review.tsx`)

**Files:** Modify `src/frontend/src/api.ts`, `src/frontend/src/pages/Review.tsx`, `src/frontend/src/pages/Review.test.tsx`.

- [ ] **Step 1: Write the failing test**

```typescript
// In src/frontend/src/pages/Review.test.tsx, set the mocked getPlan's recommendation
// to include a robust block, then assert the bands render. Add to the recommendation
// object used by the api mock:
//   robust: { robust_feasible: true, cvar_energy_kwh: 30500,
//     confidence_bands: { inlet_temp_max_c: { p50: 25, p90: 25.8, max: 26.2 },
//                         total_hvac_energy_kwh: { p50: 30000, p90: 31000, max: 31500 } },
//     n_scenarios: 4, calibration_version: 'weeks-3' }
it('shows robust confidence bands when present', async () => {
  render(<Review planId="plan-1" />);   // match the existing render signature
  expect(await screen.findByText(/Confidence Bands/i)).toBeInTheDocument();
  expect(await screen.findByText(/4 scenarios/i)).toBeInTheDocument();
});
```
(Match the existing Review.test.tsx render call + api-mock shape exactly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run test -- --run src/pages/Review.test.tsx 2>&1 | tail -6`
Expected: FAIL (no "Confidence Bands").

- [ ] **Step 3: Implement**

In `src/frontend/src/api.ts`, extend the `Recommendation` interface with an optional robust block:
```typescript
export interface Recommendation {
  status: string;
  setpoints: Record<string, number>;
  predicted_kpis: Record<string, number | null>;
  robust?: {
    robust_feasible: boolean;
    cvar_energy_kwh: number;
    confidence_bands: Record<string, { p50: number; p90: number; max: number }>;
    n_scenarios: number;
    calibration_version: string | null;
  } | null;
}
```
In `src/frontend/src/pages/Review.tsx`: extract `const robust = rec?.robust;` (near the existing `rec`/`kpi` extraction), and after the KPI Comparison card render a **"Confidence Bands"** card when `robust?.confidence_bands` exists — a small table over `Object.entries(robust.confidence_bands)` showing key, p50, p90, max; a header line `{robust.n_scenarios} scenarios · {robust.robust_feasible ? '✓ robust-feasible' : '⚠ not robust-feasible'}`. Reuse the existing `bracket-card`/table styling. Guard every field with optional chaining so a missing/sparse block never crashes.

- [ ] **Step 4: Build + test**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: build clean; all pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/frontend/src/api.ts src/frontend/src/pages/Review.tsx src/frontend/src/pages/Review.test.tsx
git commit -m "feat(dtwin): web Confidence Bands panel (robust scenarios)"
```

---

## Task 9: P2c recalibrator seam (`recalibrator.py`)

**Files:** Create `src/planner/recalibrator.py`; Test `src/tests/test_recalibrator.py`.

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_recalibrator.py
from planner.recalibrator import recalibrate
from planner.calibrator import Calibration


def test_recalibrate_is_a_documented_noop_seam():
    cal = Calibration(bias={"inlet_temp_max_c": 1.0}, sigma={"inlet_temp_max_c": 0.5},
                      n_weeks=3, version="weeks-3")
    # v1 seam: not yet implemented -> returns None regardless of inputs
    assert recalibrate(cal, history=[{"week_start": "2013-11-11"}]) is None
    assert recalibrate(cal, history=[], min_weeks=8) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recalibrator.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.recalibrator'`.

- [ ] **Step 3: Implement (create `src/planner/recalibrator.py`)**

```python
"""P2c seam: future EnergyPlus parameter recalibration — tune the twin's physical
params toward the plant once enough realized weeks accumulate (drift-triggered).
v1 is a documented NO-OP; the P2a output-residual Calibration covers the gap until
this is implemented. Wiring a real implementation behind this signature is P2c."""
from __future__ import annotations

from typing import Optional

from planner.calibrator import Calibration


def recalibrate(calibration: Calibration, history: list,
                min_weeks: int = 8) -> Optional[dict]:
    """Return EnergyPlus model-parameter updates once enough realized weeks +
    drift warrant a physics recalibration; v1 always returns None (seam only)."""
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_recalibrator.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/planner/recalibrator.py src/tests/test_recalibrator.py
git commit -m "feat(dtwin): P2c recalibrator seam (documented no-op stub)"
```

---

## Task 10: Integration test + full-suite verification

**Files:** Create `src/tests/integration/test_robust_rerank.py`; then run everything.

- [ ] **Step 1: Write the marked integration test**

```python
# src/tests/integration/test_robust_rerank.py
import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_robust_rerank_over_two_scenarios(tmp_path):
    """2-scenario robust re-rank of 2 finalists on a 1-day window (real EnergyPlus)."""
    import pickle
    import pandas as pd
    from planner.robust import make_oracle_robust_rerank, RobustResult
    from planner.oracle import OracleConfig
    from planner.forecaster import StatisticalForecaster
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    fc_cfg = pickle.loads(Path("models/forecaster.pkl").read_bytes())
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    forecast = forecaster.forecast(date(2013, 11, 11), 1 * 24 * 4)

    class _Cfg:
        n_workers = 1
        timesteps_per_hour = 4

    finalists = [
        (Setpoints(20.0, 7.05, 13.0), WeeklyKPI(0, 1.2, 25.0, 0, 0, True, 0, 0, 0), 0.0),
        (Setpoints(22.0, 7.05, 14.0), WeeklyKPI(0, 1.2, 25.5, 0, 0, True, 0, 0, 0), 0.0),
    ]
    fn = make_oracle_robust_rerank("configs/dt/dt.prototxt", _Cfg(), None,
                                   ObjectiveWeights(), n_scenarios=2, log_root=str(tmp_path))
    rr = fn(finalists, forecast=forecast)
    assert isinstance(rr, RobustResult) and rr.n_scenarios == 2
    assert rr.cvar_energy_kwh > 0
    assert "inlet_temp_max_c" in rr.confidence_bands
```
(Verify the `WeeklyKPI(...)` positional args match `types.py`; use keywords if unsure.)

- [ ] **Step 2: Run it under Docker (optional but recommended)**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_robust_rerank.py -m integration -q"`
Expected: PASS (2 scenario × 2 finalist = 4 short EnergyPlus runs; a few minutes). Auto-deselected in the normal suite.

- [ ] **Step 3: Full backend + frontend suites**

Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q 2>&1 | tail -2`
Run: `cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run build && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "`
Expected: all backend pass (+5 deselected: the 4 prior integration + this one), frontend build clean + all pass.

- [ ] **Step 4: Commit**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin
git add src/tests/integration/test_robust_rerank.py
git commit -m "test(dtwin): integration — 2-scenario robust re-rank under Docker"
```

---

## Self-review notes

- **Spec coverage (P2b §6.3 scenarios, §6.4 worst-case feasibility + CVaR, §6.6 confidence bands, §7 schema 1.1 robust block, §9 M6–M7; P2c §5.5 seam):** finalists exposed (Task 1) ✓; scenario generation + σ-spread (Task 2) ✓; robust_select worst-case + CVaR + bands (Task 3) ✓; scenario orchestration over EnergyPlus (Task 4) ✓; pipeline wiring (Task 5) ✓; schema 1.1 robust block (Task 6) ✓; production wiring (Task 7) ✓; UI bands (Task 8) ✓; recalibrator seam (Task 9) ✓; integration test (Task 10) ✓.
- **Deferred (noted):** the multi-week loop-convergence test (residual shrinks over simulated weeks) flagged in the P2a final review — still a good capstone; out of scope here.
- **Type consistency:** `_Scored = (Setpoints, WeeklyKPI, float)` used identically in Tasks 1,3,4,5; `RobustResult` fields used identically in Tasks 3,5,6,7; `robust_rerank_fn(finalists, forecast) -> RobustResult` signature consistent (Task 4 produces it, Task 5 consumes it, Task 7 builds it); robust-block keys (`robust_feasible, cvar_energy_kwh, confidence_bands, n_scenarios, calibration_version`) identical across recommendation.py (Task 6), pipeline (Task 5), api.ts/Review (Task 8); band keys (`total_hvac_energy_kwh, inlet_temp_max_c, pue_mean`) consistent with `predicted_kpis`.
- **Backward compatibility:** `beam_finalists` has a default; `robust_rerank_fn`/`calibration` default None → schema stays "1.0" with no robust block → existing behavior + tests unchanged. The robust stage runs only on the top-K beam (cost-bounded: N scenarios × K finalists EnergyPlus runs).
- **Cost note:** the EnergyPlus cost (N×K full-week runs on finalists) is real; `n_scenarios` defaults to 4 and is a `params` knob. `log()` is not applicable (plan doc), but the spec's "no silent caps" guidance is honored by surfacing `n_scenarios` in the recommendation's robust block.
