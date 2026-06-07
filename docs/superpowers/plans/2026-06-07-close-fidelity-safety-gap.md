# Close the Fidelity/Safety Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekly deploy decision trustworthy under twin≠plant — no plan can be approved or deployed unless it is demonstrably non-breaching on the plant it runs against, the calibration learning loop stops self-poisoning, and the expert reviews an independent replay.

**Architecture:** Enforce "feasible == robust-feasible" in ONE place — the status state machine — so `approve`/`deploy`/`PATCH` all honor it. Add a deploy-time backstop that re-checks the real deploy plant. Thread the raw (uncalibrated) winner KPI into the recommendation so calibration residuals are fit honestly. Make pre-validation an independent oracle replay that emits a report + trajectory.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), pytest, FastAPI, dctwin/EnergyPlus 9.5 via Docker (integration only).

**Spec:** `docs/superpowers/specs/2026-06-07-close-fidelity-safety-gap-design.md`

**Conventions for every task below:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`
- Run all commands from `/mnt/lv/home/hoanghuy/newcode/dctwin/src`.
- Unit tests: `$PY -m pytest <path> -v` (the default `-m 'not integration'` filter applies).
- Commit after each task. Branch is `feat/close-fidelity-safety-gap` (already created).

---

## File map (what changes and why)

| File | Change | Task |
|---|---|---|
| `webapp/status.py` | new statuses `blocked_unsafe`/`deploy_blocked`; remove `infeasible_fallback→approved` | 1 |
| `planner/pipeline.py` | robust-feasibility decides status; emit `blocked_unsafe`; thread raw KPI | 2, 6 |
| `webapp/jobs.py` | deploy-time backstop; `advance_calibration` fits against raw | 3, 7 |
| `planner/calibrator.py` | σ-prior + residual clip in `fit_calibration` | 4 |
| `planner/beam_search.py` | retain raw (pre-calibration) KPI in scored tuples + `PlanResult` | 5 |
| `planner/robust.py` | carry `winner_kpi_raw` through `RobustResult` | 6 |
| `planner/recommendation.py` | `predicted_kpis_raw` + schema 1.2 | 6 |
| `planner/kpi.py` | `step_trajectory()` per-step series | 8 |
| `planner/trajectory.py` (new) | `write_trajectory_csv()` | 8 |
| `prevalidation.py` | independent replay; emit report + trajectory | 9 |
| `planner/mock_evaluator.py` | `replay_with_trajectory()` for tests | 9 |
| `ai_trajectory_test.py` | `policy="ai"` | 9 |
| `webapp/main.py` | PATCH status-gate + invalidation; approve blocked on `needs_revalidation`; auto pre-validation | 9, 11 |
| `webapp/auth.py` | fail-closed `from_env` | 12 |
| `tests/integration/test_fidelity_gate.py` (new) | Docker regression | 13 |
| `docs/fidelity-acceptance.md` (new) | realized acceptance run | 13 |

---

## Task 1: Status state machine — new statuses, close the approval hole (spec §4.1b)

**Files:**
- Modify: `webapp/status.py`
- Test: `tests/test_status.py`

- [ ] **Step 1: Update the existing test to the new contract**

Replace the whole body of `tests/test_status.py` with:

```python
from webapp.status import PlanStatus, can_transition


def test_allowed_transitions():
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.APPROVED, PlanStatus.DEPLOYING)
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOYED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_FAILED)


def test_unsafe_statuses_are_not_approvable():
    # the safety property: a plan that is not robust-feasible cannot be approved
    assert not can_transition(PlanStatus.BLOCKED_UNSAFE, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.BLOCKED_UNSAFE, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.REJECTED)


def test_deploy_blocked_allows_retry_or_reject():
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_BLOCKED)
    assert can_transition(PlanStatus.DEPLOY_BLOCKED, PlanStatus.DEPLOYING)
    assert can_transition(PlanStatus.DEPLOY_BLOCKED, PlanStatus.REJECTED)


def test_forbidden_transitions():
    assert not can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.DEPLOYED)
    assert not can_transition(PlanStatus.REJECTED, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.DEPLOYED, PlanStatus.APPROVED)
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `$PY -m pytest tests/test_status.py -v`
Expected: FAIL — `AttributeError: type object 'PlanStatus' has no attribute 'BLOCKED_UNSAFE'`.

- [ ] **Step 3: Implement the new statuses + transition table**

Replace `webapp/status.py` with:

```python
"""Plan status values + the allowed transition graph (the outer-loop state machine)."""
from __future__ import annotations


class PlanStatus:
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    PENDING_APPROVAL = "pending_approval"
    INFEASIBLE_FALLBACK = "infeasible_fallback"   # nominal search found nothing feasible
    BLOCKED_UNSAFE = "blocked_unsafe"             # robust re-rank: no finalist is safe
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    DEPLOY_FAILED = "deploy_failed"               # the deploy job crashed
    DEPLOY_BLOCKED = "deploy_blocked"             # approved plan breached on the real plant


# expert/operator-driven transitions (the worker sets queued/running/failed/deploy_* itself)
_ALLOWED = {
    PlanStatus.PENDING_APPROVAL: {PlanStatus.APPROVED, PlanStatus.REJECTED},
    # unsafe plans are NOT approvable — only rejectable (the gate's single source of truth)
    PlanStatus.INFEASIBLE_FALLBACK: {PlanStatus.REJECTED},
    PlanStatus.BLOCKED_UNSAFE: {PlanStatus.REJECTED},
    PlanStatus.APPROVED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
    PlanStatus.DEPLOYING: {PlanStatus.DEPLOYED, PlanStatus.DEPLOY_FAILED,
                           PlanStatus.DEPLOY_BLOCKED},
    PlanStatus.DEPLOY_FAILED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
    PlanStatus.DEPLOY_BLOCKED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
}


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `$PY -m pytest tests/test_status.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Check nothing else asserted the old hole**

Run: `$PY -m pytest tests/test_api.py tests/test_public_api.py -v`
Expected: PASS. If any test relied on `infeasible_fallback → approved`, update it to expect a 409.

- [ ] **Step 6: Commit**

```bash
git add webapp/status.py tests/test_status.py
git commit -m "feat(dtwin): close the approval hole — unsafe statuses non-approvable + deploy_blocked"
```

---

## Task 2: Plan-time gate — robust feasibility decides status (spec §4.1a)

**Files:**
- Modify: `planner/pipeline.py:49-72`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test for the blocked_unsafe path**

Append to `tests/test_pipeline.py`:

```python
def test_run_weekly_plan_blocks_when_not_robust_feasible():
    chosen = Setpoints(21.0, 12.0, 14.0)
    chosen_kpi = WeeklyKPI(total_hvac_energy_kwh=999.0, pue_mean=1.1, inlet_temp_max=27.0,
                           inlet_violation_steps=5, rh_violation_steps=0, feasible=False,
                           inlet_excess_degc_steps=0.0, rh_excursion_steps=0.0, zone_temp_band_steps=0.0)

    def fake_rerank(finalists, forecast):
        return RobustResult(winner=chosen, winner_kpi=chosen_kpi, robust_feasible=False,
                            cvar_energy_kwh=2000.0,
                            confidence_bands={"inlet_temp_max_c": {"p50": 26.5, "p90": 27.5, "max": 28.0}},
                            n_scenarios=3)

    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        robust_rerank_fn=fake_rerank,
    )
    assert rec["status"] == "blocked_unsafe"
    assert rec["robust"]["robust_feasible"] is False
    # the robust winner (least-bad finalist) is still surfaced, not the coolest-corner fallback
    assert rec["setpoints"]["crah_supply_air_temperature_c"] == 21.0
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_pipeline.py::test_run_weekly_plan_blocks_when_not_robust_feasible -v`
Expected: FAIL — `assert 'pending_approval' == 'blocked_unsafe'` (current code ignores robust feasibility).

- [ ] **Step 3: Rewrite the status-decision block in `run_weekly_plan`**

In `planner/pipeline.py`, replace lines 49-72 (from `robust = None` through the `return build_recommendation(...)`) with:

```python
    robust = None
    if robust_rerank_fn is not None and result.beam_finalists:
        robust = robust_rerank_fn(result.beam_finalists, forecast)

    if robust is not None:
        # when the robust ensemble ran, robust feasibility is decisive
        best, kpi = robust.winner, robust.winner_kpi
        status = "pending_approval" if robust.robust_feasible else "blocked_unsafe"
    elif result.feasible:
        best, kpi, status = result.best, result.best_kpi, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        fb_kpi = evaluator.evaluate([fb], forecast)[0]
        kpi = calibration.apply(fb_kpi) if calibration is not None else fb_kpi
        best, status = fb, "infeasible_fallback"

    return build_recommendation(
        setpoints=best, kpi=kpi, week_start=request.week_start, days=request.days,
        forecast_method=getattr(forecast, "method", "persistence"),
        search_meta={"evals": result.evals, "beam_width": beam.beam_width, "levels": beam.levels},
        baseline_energy_kwh=baseline_energy_kwh, status=status,
        robust_feasible=(robust.robust_feasible if robust else None),
        cvar_energy_kwh=(robust.cvar_energy_kwh if robust else None),
        confidence_bands=(robust.confidence_bands if robust else None),
        n_scenarios=(robust.n_scenarios if robust else None),
        calibration_version=(calibration.version if calibration is not None else None),
    )
```

(Note: the old code did `result.best, result.best_kpi = robust.winner, robust.winner_kpi` then branched on `result.feasible` — which is the *nominal* feasibility and never the robust one. The new code makes robust feasibility decisive when the ensemble ran.)

- [ ] **Step 4: Run the pipeline tests, verify all pass**

Run: `$PY -m pytest tests/test_pipeline.py -v`
Expected: PASS — the new `blocked_unsafe` test plus the existing `applies_robust_rerank` (robust_feasible=True → pending_approval) and `without_robust_unchanged`.

- [ ] **Step 5: Commit**

```bash
git add planner/pipeline.py tests/test_pipeline.py
git commit -m "feat(dtwin): plan-time gate — robust feasibility decides status (blocked_unsafe)"
```

---

## Task 3: Deploy-time backstop — re-check the real plant (spec §4.1c)

**Files:**
- Modify: `webapp/jobs.py:197-203`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test (inject a fake deploy_runner is not enough — test the realized-breach status rule directly)**

Append to `tests/test_jobs.py`:

```python
def test_deploy_status_blocked_on_realized_breach(tmp_path):
    from webapp.jobs import deploy_status_for
    # a realized week with inlet violations must NOT be marked 'deployed'
    assert deploy_status_for({"inlet_violation_steps": 666}) == "deploy_blocked"
    assert deploy_status_for({"inlet_violation_steps": 0}) == "deployed"
    assert deploy_status_for({}) == "deployed"  # missing key -> treat as no recorded breach
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_jobs.py::test_deploy_status_blocked_on_realized_breach -v`
Expected: FAIL — `ImportError: cannot import name 'deploy_status_for'`.

- [ ] **Step 3: Add the pure helper and wire it into `run_deploy_job`**

In `webapp/jobs.py`, add this module-level function (place it just above `run_deploy_job`):

```python
def deploy_status_for(realized: dict) -> str:
    """0-tolerance hard cap (spec §4.3): any realized inlet violation on the real
    deploy plant blocks the deploy, even though we still record + learn from it."""
    return "deploy_blocked" if realized.get("inlet_violation_steps", 0) > 0 else "deployed"
```

Then in `run_deploy_job`, replace the final block (lines 197-203, from `rec = deploy(...)` to `store.set_status(plan_id, "deployed")`) with:

```python
    rec = deploy(rec_path, plant_oracle, forecast=forecast)
    realized = rec["realized_kpis"]
    store.save_realized(plan_id, realized)
    # ALWAYS learn from the realized week (esp. the bad ones) ...
    advance_history(realized, week_start, "data/realized_history.csv")
    advance_calibration(rec.get("predicted_kpis", {}), realized, week_start,
                        "data/calibration_history.json")
    recompute_calibration("data/calibration_history.json", "data/calibration.json")
    # ... but only call the week 'deployed' if it did NOT breach on the real plant.
    store.set_status(plan_id, deploy_status_for(realized))
```

- [ ] **Step 4: Run the jobs tests, verify pass**

Run: `$PY -m pytest tests/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/jobs.py tests/test_jobs.py
git commit -m "feat(dtwin): deploy-time backstop — realized breach -> deploy_blocked (still learns)"
```

---

## Task 4: Calibrator σ-prior + residual clip (spec §4.3a)

**Files:**
- Modify: `planner/calibrator.py:62-76`
- Test: `tests/test_calibrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_calibrator.py`:

```python
from planner.calibrator import SIGMA_PRIOR, RESIDUAL_CLIP


def test_sigma_floor_at_cold_start():
    # a single deploy must NOT yield sigma=0 (which would brick the next plan)
    hist = [{"week_start": "2013-11-11",
             "predicted": {"total_hvac_energy_kwh": 100.0, "pue_mean": 1.2, "inlet_temp_max_c": 24.0},
             "realized":  {"total_hvac_energy_kwh": 130.0, "pue_mean": 1.2, "inlet_temp_max_c": 28.0}}]
    cal = fit_calibration(hist)
    assert cal.sigma["inlet_temp_max_c"] == SIGMA_PRIOR["inlet_temp_max_c"]
    assert cal.sigma["inlet_temp_max_c"] > 0.0


def test_residual_clip_bounds_one_wild_week():
    # an absurd single residual is winsorized to the clip bound before it becomes the bias
    hist = [{"week_start": "2013-11-11",
             "predicted": {"inlet_temp_max_c": 24.0},
             "realized":  {"inlet_temp_max_c": 24.0 + 10 * RESIDUAL_CLIP["inlet_temp_max_c"]}}]
    cal = fit_calibration(hist)
    assert cal.bias["inlet_temp_max_c"] == RESIDUAL_CLIP["inlet_temp_max_c"]


def test_sigma_shrinks_toward_sample_as_n_grows():
    # with many consistent weeks, sample std (here ~1.0) dominates the prior
    hist = []
    for i, r in enumerate([102.0, 100.0, 102.0, 100.0, 102.0, 100.0]):
        hist.append({"week_start": f"2013-11-{i:02d}",
                     "predicted": {"total_hvac_energy_kwh": 101.0},
                     "realized":  {"total_hvac_energy_kwh": r}})
    cal = fit_calibration(hist)
    assert 0.9 <= cal.sigma["total_hvac_energy_kwh"] <= 1.1
```

- [ ] **Step 2: Run them, verify they fail**

Run: `$PY -m pytest tests/test_calibrator.py -k "sigma or clip" -v`
Expected: FAIL — `ImportError: cannot import name 'SIGMA_PRIOR'`.

- [ ] **Step 3: Implement σ-prior + clip**

In `planner/calibrator.py`, add constants under `CALIB_KEYS` (after line 18):

```python
# Conservative per-KPI prior sigma (a floor at cold-start) and per-residual clip
# (winsorize so one wild week can't dominate the bias). Spec §6.1.
SIGMA_PRIOR = {"total_hvac_energy_kwh": 5000.0, "pue_mean": 0.05, "inlet_temp_max_c": 1.0}
RESIDUAL_CLIP = {"total_hvac_energy_kwh": 50000.0, "pue_mean": 0.5, "inlet_temp_max_c": 3.0}
```

Then replace `fit_calibration` (lines 62-76) with:

```python
def fit_calibration(history: list) -> Calibration:
    bias, sigma = {}, {}
    for key in CALIB_KEYS:
        clip = RESIDUAL_CLIP.get(key, float("inf"))
        res = []
        for e in history:
            p = e.get("predicted", {}).get(key)
            r = e.get("realized", {}).get(key)
            if p is not None and r is not None:
                res.append(max(-clip, min(clip, r - p)))   # winsorized residual
        if res:
            m = sum(res) / len(res)
            bias[key] = m
            prior = SIGMA_PRIOR.get(key, 0.0)
            if len(res) > 1:
                sample = (sum((x - m) ** 2 for x in res) / len(res)) ** 0.5
                # inverse-variance blend: prior dominates at n=1, sample as n grows
                n = len(res)
                sigma[key] = (prior + (n - 1) * sample) / n
            else:
                sigma[key] = prior                          # cold-start floor, never 0
    n = len(history)
    return Calibration(bias=bias, sigma=sigma, n_weeks=n, version=f"weeks-{n}")
```

- [ ] **Step 4: Run the calibrator tests, verify pass**

Run: `$PY -m pytest tests/test_calibrator.py -v`
Expected: PASS for the new tests. NOTE: the existing `test_fit_calibration_bias_and_sigma` asserts `sigma["total_hvac_energy_kwh"] == 1.0` and `sigma["inlet_temp_max_c"] == 0.0`. Update those two assertions to the blended values: with n=2, energy residuals (2.0, 4.0) → sample=1.0, prior=5000 → `(5000 + 1*1.0)/2 = 2500.5`; inlet residuals (1.0, 1.0) → sample=0.0, prior=1.0 → `(1.0 + 1*0.0)/2 = 0.5`. So change them to `math.isclose(cal.sigma["total_hvac_energy_kwh"], 2500.5)` and `cal.sigma["inlet_temp_max_c"] == 0.5`.

- [ ] **Step 5: Commit**

```bash
git add planner/calibrator.py tests/test_calibrator.py
git commit -m "feat(dtwin): calibrator sigma-prior + residual clip (no more n=1 sigma=0 poison)"
```

---

## Task 5: Retain the raw (pre-calibration) KPI in the beam (spec §4.3b, part 1)

**Files:**
- Modify: `planner/beam_search.py`
- Test: `tests/test_beam_search.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_beam_search.py` (imports `Calibration` from calibrator):

```python
from planner.calibrator import Calibration


def test_plan_result_exposes_raw_uncalibrated_kpi():
    from planner.beam_search import BeamPlanner, BeamConfig
    from planner.mock_evaluator import MockEvaluator, MockSurface
    from planner.types import DEFAULT_SEARCH_SPACE
    cal = Calibration(bias={"inlet_temp_max_c": 2.0}, sigma={"inlet_temp_max_c": 1.0},
                      n_weeks=1, version="weeks-1")
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(MockSurface(inlet_cap=999.0)),
                          config=BeamConfig(grid=3, beam_width=2, levels=1), calibration=cal)
    result = planner.plan()
    # calibrated best_kpi has the +2.0 inlet bias; raw does not
    assert result.best_kpi.inlet_temp_max == result.best_kpi_raw.inlet_temp_max + 2.0
    # finalists carry the raw kpi as a 4th tuple element
    assert len(result.beam_finalists[0]) == 4
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_beam_search.py::test_plan_result_exposes_raw_uncalibrated_kpi -v`
Expected: FAIL — `AttributeError: 'PlanResult' object has no attribute 'best_kpi_raw'`.

- [ ] **Step 3: Thread raw through `_score_batch`, `PlanResult`, and `plan()`**

In `planner/beam_search.py`:

(a) Update the `_Scored` comment (line 35-36) to:
```python
# a scored candidate: (setpoints, calibrated_kpi, score, raw_kpi)
_Scored = tuple[Setpoints, WeeklyKPI, float, WeeklyKPI]
```

(b) Add a field to `PlanResult` — insert `best_kpi_raw` after `history` (line 31) and before `beam_finalists`:
```python
@dataclass
class PlanResult:
    best: Setpoints
    best_kpi: WeeklyKPI
    best_score: float
    evals: int
    feasible: bool
    history: list[float]     # best score after each level
    best_kpi_raw: WeeklyKPI = None   # the winner's pre-calibration KPI (for residual fitting)
    beam_finalists: list = field(default_factory=list)   # final beam: list[_Scored]
```

(c) Replace `_score_batch` (lines 136-141) with:
```python
    def _score_batch(self, candidates: Sequence[Setpoints], forecast,
                     on_result: Optional[Callable[[], None]] = None) -> list[_Scored]:
        raw_kpis = self.evaluator.evaluate(candidates, forecast, on_result=on_result)
        if self.calibration is not None:
            cal_kpis = [self.calibration.apply(k) for k in raw_kpis]
        else:
            cal_kpis = raw_kpis
        return [(c, kc, score(kc, self.weights), kr)
                for c, kc, kr in zip(candidates, cal_kpis, raw_kpis)]
```

(d) Fix the 3-tuple unpack in the refine loop (line 112):
```python
            for s, _kpi, _sc, _raw in beam:
```

(e) Fix the final unpack + `PlanResult` construction (lines 131-134):
```python
        best_s, best_kpi, best_sc, best_raw = beam[0]
        feasible = best_sc != INFEASIBLE
        return PlanResult(best_s, best_kpi, best_sc, evals, feasible, history,
                          best_kpi_raw=best_raw, beam_finalists=list(beam))
```

- [ ] **Step 4: Run the beam tests, verify pass**

Run: `$PY -m pytest tests/test_beam_search.py -v`
Expected: PASS. If any existing test unpacks a finalist as a 3-tuple, update it to 4 elements (or index `[0]`/`[1]`).

- [ ] **Step 5: Commit**

```bash
git add planner/beam_search.py tests/test_beam_search.py
git commit -m "feat(dtwin): beam search retains the raw pre-calibration KPI"
```

---

## Task 6: Thread raw KPI to the recommendation — schema 1.2 (spec §4.3b, part 2)

**Files:**
- Modify: `planner/robust.py`, `planner/pipeline.py`, `planner/recommendation.py`
- Test: `tests/test_robust.py`, `tests/test_recommendation.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing recommendation test**

Append to `tests/test_recommendation.py`:

```python
def test_build_recommendation_emits_raw_kpis_schema_1_2():
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from datetime import date
    cal_kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=27.0,
                        inlet_violation_steps=1, rh_violation_steps=0, feasible=True)
    raw_kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=25.0,
                        inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(
        setpoints=Setpoints(22.0, 7.0, 15.0), kpi=cal_kpi, week_start=date(2013, 11, 11),
        days=7, forecast_method="persistence", search_meta={"evals": 1},
        raw_kpi=raw_kpi)
    assert rec["schema_version"] == "1.2"
    assert rec["predicted_kpis"]["inlet_temp_max_c"] == 27.0      # calibrated (shown)
    assert rec["predicted_kpis_raw"]["inlet_temp_max_c"] == 25.0  # raw (for fitting)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_recommendation.py::test_build_recommendation_emits_raw_kpis_schema_1_2 -v`
Expected: FAIL — `TypeError: build_recommendation() got an unexpected keyword argument 'raw_kpi'`.

- [ ] **Step 3: Add `raw_kpi`, `robust_substituted`, `scenario_diagnostics` to `build_recommendation`**

In `planner/recommendation.py`, add the parameters to the signature (after `calibration_version`):
```python
    calibration_version: Optional[str] = None,
    raw_kpi: Optional[WeeklyKPI] = None,
    robust_substituted: bool = False,
    scenario_diagnostics: Optional[list] = None,
) -> dict:
```

Add the two diagnostic keys to the existing robust block (inside `if robust_feasible is not None:`, lines 70-76):
```python
        rec["robust"] = {
            "robust_feasible": robust_feasible,
            "robust_substituted": robust_substituted,
            "cvar_energy_kwh": cvar_energy_kwh,
            "confidence_bands": confidence_bands or {},
            "scenario_diagnostics": scenario_diagnostics or [],
            "n_scenarios": n_scenarios,
            "calibration_version": calibration_version,
        }
```

And before `return rec`, insert (the schema bump goes last so 1.2 wins over the robust block's 1.1):
```python
    if raw_kpi is not None:
        rec["predicted_kpis_raw"] = {
            "total_hvac_energy_kwh": raw_kpi.total_hvac_energy_kwh,
            "pue_mean": raw_kpi.pue_mean,
            "inlet_temp_max_c": raw_kpi.inlet_temp_max,
            "inlet_violation_steps": raw_kpi.inlet_violation_steps,
        }
        rec["schema_version"] = "1.2"
```

- [ ] **Step 4: Add `winner_kpi_raw` + `robust_substituted` + `scenario_diagnostics` to `RobustResult` + `robust_select`**

In `planner/robust.py`, add three fields to `RobustResult` (after `n_scenarios`, all with defaults so existing constructions don't break; `Optional` is already imported):
```python
@dataclass
class RobustResult:
    winner: Setpoints
    winner_kpi: WeeklyKPI            # the calibrated NOMINAL kpi (twin's best estimate)
    robust_feasible: bool            # feasible in EVERY scenario
    cvar_energy_kwh: float           # CVaR_alpha of energy across scenarios
    confidence_bands: dict           # {kpi_key: {"p50","p90","max"}}
    n_scenarios: int
    winner_kpi_raw: WeeklyKPI = None        # the winner's pre-calibration nominal kpi
    robust_substituted: bool = False        # winner != the energy-optimal beam finalist
    scenario_diagnostics: Optional[list] = None   # per-scenario inlet/feasibility for the winner
```

In `robust_select`, replace the `return RobustResult(...)` (lines 88-91) with (the finalists are score-sorted, so index 0 is the energy-optimal one; defensive on 3- vs 4-tuples):
```python
    raw = finalists[win][3] if len(finalists[win]) > 3 else finalists[win][1]
    diagnostics = [
        {"scenario": j,
         "inlet_temp_max_c": scenario_kpis[win][j].inlet_temp_max,
         "feasible": is_feasible(scenario_kpis[win][j], weights)}
        for j in range(n_scen)
    ]
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=n_scen, winner_kpi_raw=raw,
        robust_substituted=(win != 0), scenario_diagnostics=diagnostics)
```

- [ ] **Step 5: Pass raw through `run_weekly_plan`**

In `planner/pipeline.py`, in the status-decision block from Task 2, set a `raw` alongside `kpi` in each branch and pass it to `build_recommendation`:
```python
    if robust is not None:
        best, kpi = robust.winner, robust.winner_kpi
        raw = robust.winner_kpi_raw or robust.winner_kpi
        status = "pending_approval" if robust.robust_feasible else "blocked_unsafe"
    elif result.feasible:
        best, kpi, raw, status = result.best, result.best_kpi, result.best_kpi_raw, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        fb_kpi = evaluator.evaluate([fb], forecast)[0]
        kpi = calibration.apply(fb_kpi) if calibration is not None else fb_kpi
        best, raw, status = fb, fb_kpi, "infeasible_fallback"
```
Then add these keyword args to the `build_recommendation(...)` call:
```python
        raw_kpi=raw,
        robust_substituted=(robust.robust_substituted if robust else False),
        scenario_diagnostics=(robust.scenario_diagnostics if robust else None),
```

- [ ] **Step 6: Update the two existing pipeline tests for schema 1.2**

In `tests/test_pipeline.py`: `test_run_weekly_plan_applies_robust_rerank` now produces schema `"1.2"` (raw is threaded). Change its `assert rec["schema_version"] == "1.1"` to `== "1.2"`, and add `assert rec["predicted_kpis_raw"]["total_hvac_energy_kwh"] == 999.0`. The `fake_rerank` returns a `RobustResult` without `winner_kpi_raw` (defaults to None) → pipeline falls back to `winner_kpi`, so raw == winner_kpi (999.0). Leave `test_run_weekly_plan_without_robust_unchanged` — with no robust and a feasible MockEvaluator it still threads `result.best_kpi_raw`, so update its assert to `rec["schema_version"] == "1.2"` and drop the `"robust" not in rec` check to just `assert "robust" not in rec`.

- [ ] **Step 7: Run all affected unit tests, verify pass**

Run: `$PY -m pytest tests/test_recommendation.py tests/test_robust.py tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add planner/robust.py planner/pipeline.py planner/recommendation.py tests/test_recommendation.py tests/test_robust.py tests/test_pipeline.py
git commit -m "feat(dtwin): thread raw uncalibrated KPI into recommendation (schema 1.2)"
```

---

## Task 7: Fit calibration residuals against the raw prediction (spec §4.3b, part 3)

**Files:**
- Modify: `webapp/jobs.py` (`run_deploy_job`)
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_residual_source_prefers_raw_predicted():
    from webapp.jobs import residual_predicted_for
    rec = {"predicted_kpis": {"inlet_temp_max_c": 27.0},        # calibrated (already +2)
           "predicted_kpis_raw": {"inlet_temp_max_c": 25.0}}    # raw
    assert residual_predicted_for(rec) == {"inlet_temp_max_c": 25.0}
    # backward-compat: old recs without raw fall back to predicted_kpis
    assert residual_predicted_for({"predicted_kpis": {"inlet_temp_max_c": 25.0}}) == {"inlet_temp_max_c": 25.0}
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_jobs.py::test_residual_source_prefers_raw_predicted -v`
Expected: FAIL — `ImportError: cannot import name 'residual_predicted_for'`.

- [ ] **Step 3: Add the helper and use it in `run_deploy_job`**

In `webapp/jobs.py`, add near `deploy_status_for`:
```python
def residual_predicted_for(rec: dict) -> dict:
    """Calibration residuals must be fit against the RAW (uncalibrated) prediction,
    not the already-corrected predicted_kpis (which would double-correct). Spec §4.3b."""
    return rec.get("predicted_kpis_raw") or rec.get("predicted_kpis", {})
```

Then in `run_deploy_job`, change the `advance_calibration` call to use it:
```python
    advance_calibration(residual_predicted_for(rec), realized, week_start,
                        "data/calibration_history.json")
```

- [ ] **Step 4: Run the jobs tests, verify pass**

Run: `$PY -m pytest tests/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/jobs.py tests/test_jobs.py
git commit -m "fix(dtwin): fit calibration residuals against raw prediction (no double-correction)"
```

---

## Task 8: Per-step trajectory series + CSV writer (spec §4.2)

**Files:**
- Modify: `planner/kpi.py`
- Create: `planner/trajectory.py`
- Test: `tests/test_trajectory.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_trajectory.py`:

```python
from planner.kpi import StepSample, OracleSettings, step_trajectory
from planner.trajectory import write_trajectory_csv


def _smp(power, it, inlet):
    return StepSample(total_power_w=power, it_power_w=it, inlet_temps=[inlet])


def test_step_trajectory_rows():
    samples = [_smp(1200.0, 1000.0, 24.0), _smp(1300.0, 1000.0, 25.0)]
    rows = step_trajectory(samples, hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    assert len(rows) == 2
    assert rows[0]["step"] == 0
    assert rows[0]["inlet_temp_max_c"] == 24.0
    assert rows[0]["hvac_power_kw"] == 0.2          # (1200-1000)/1000
    assert abs(rows[1]["pue"] - 1.3) < 1e-9         # 1300/1000


def test_write_trajectory_csv(tmp_path):
    rows = [{"step": 0, "inlet_temp_max_c": 24.0, "hvac_power_kw": 0.2, "pue": 1.2}]
    out = tmp_path / "trajectory_ai.csv"
    write_trajectory_csv(rows, str(out))
    text = out.read_text().splitlines()
    assert text[0] == "step,inlet_temp_max_c,hvac_power_kw,pue"
    assert text[1] == "0,24.0,0.2,1.2"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `$PY -m pytest tests/test_trajectory.py -v`
Expected: FAIL — `ImportError: cannot import name 'step_trajectory'`.

- [ ] **Step 3: Add `step_trajectory` to `planner/kpi.py`**

Append to `planner/kpi.py`:

```python
def step_trajectory(samples: list[StepSample], hours_per_step: float,
                    settings: OracleSettings) -> list[dict]:
    """Per-step series for the pre-validation trajectory CSV. Applies the same
    warmup discard as aggregate_kpi so the plot matches the scored window."""
    s = settings
    if len(samples) > s.warmup_steps:
        samples = samples[s.warmup_steps:]
    rows = []
    for i, smp in enumerate(samples):
        hvac_w = smp.total_power_w - smp.it_power_w
        rows.append({
            "step": i,
            "inlet_temp_max_c": max(smp.inlet_temps) if smp.inlet_temps else None,
            "hvac_power_kw": hvac_w / 1000.0,
            "pue": (smp.total_power_w / smp.it_power_w) if smp.it_power_w > 0 else None,
        })
    return rows
```

- [ ] **Step 4: Create `planner/trajectory.py`**

```python
"""Write a pre-validation per-step trajectory to CSV (the diagram's trajectory_*.csv)."""
from __future__ import annotations

from pathlib import Path

_COLS = ("step", "inlet_temp_max_c", "hvac_power_kw", "pue")


def write_trajectory_csv(rows: list[dict], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(_COLS)]
    for r in rows:
        lines.append(",".join("" if r.get(c) is None else str(r.get(c)) for c in _COLS))
    Path(path).write_text("\n".join(lines) + "\n")
```

- [ ] **Step 5: Run the test, verify pass**

Run: `$PY -m pytest tests/test_trajectory.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add planner/kpi.py planner/trajectory.py tests/test_trajectory.py
git commit -m "feat(dtwin): per-step trajectory series + CSV writer for pre-validation"
```

---

## Task 9: Pre-validation = independent replay; emit report + trajectory (spec §4.2)

**Files:**
- Modify: `prevalidation.py`, `planner/mock_evaluator.py`, `ai_trajectory_test.py`
- Test: `tests/test_prevalidation_gate.py`

- [ ] **Step 1: Add a trajectory-capable replay to MockEvaluator (test seam)**

In `planner/mock_evaluator.py`, add a method to `MockEvaluator` that returns a KPI plus synthetic per-step samples (so prevalidation's artifact path is unit-testable without Docker):

```python
    def replay_with_trajectory(self, setpoints, forecast=None, n_steps: int = 8):
        from planner.kpi import StepSample
        kpi = self.evaluate([setpoints], forecast)[0]
        samples = [
            StepSample(total_power_w=1200.0, it_power_w=1000.0,
                       inlet_temps=[kpi.inlet_temp_max])
            for _ in range(n_steps)
        ]
        return kpi, samples
```

- [ ] **Step 2: Write the failing prevalidation test**

Append to `tests/test_prevalidation_gate.py`:

```python
def test_run_prevalidation_independent_replay_emits_artifacts(tmp_path, monkeypatch):
    import json
    from datetime import date
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from planner.mock_evaluator import MockEvaluator, MockSurface
    import prevalidation

    # a recommendation whose stored predicted_kpis are deliberately WRONG; the
    # independent replay must recompute, not echo them.
    bad_kpi = WeeklyKPI(total_hvac_energy_kwh=1.0, pue_mean=1.0, inlet_temp_max=0.0,
                        inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(setpoints=Setpoints(22.0, 7.0, 15.0), kpi=bad_kpi,
                               week_start=date(2013, 11, 11), days=1, forecast_method="persistence",
                               search_meta={"evals": 1})
    rec_path = tmp_path / "recommendation.json"
    rec_path.write_text(json.dumps(rec))

    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    metrics = prevalidation.run_prevalidation(
        str(rec_path), evaluator=ev, baseline=Setpoints(24.0, 13.8, 13.0),
        out_dir=str(tmp_path))

    # the replay produced its OWN ai KPIs (not the bogus 1.0 stored energy).
    # validation_metrics returns FLAT keys: ai_energy_kwh, baseline_energy_kwh,
    # energy_reduction_pct, ai_pue_mean, baseline_pue_mean, ai_inlet_max_c,
    # ai_inlet_violations, passes (see planner/validation.py).
    assert metrics["ai_energy_kwh"] != 1.0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "trajectory_ai.csv").exists()
```

- [ ] **Step 3: Run it, verify it fails**

Run: `$PY -m pytest tests/test_prevalidation_gate.py::test_run_prevalidation_independent_replay_emits_artifacts -v`
Expected: FAIL — `run_prevalidation` has the old signature / reads predicted_kpis.

- [ ] **Step 4: Rewrite `run_prevalidation` as an independent replay**

Replace the body of `prevalidation.py` from `def run_prevalidation(` to the end with (keeping the existing imports of `validation_metrics`, `render_report`, `ParallelEnvOracle`, `OracleConfig`, `WeeklyKPI`, `Setpoints`, `date`, `Path`, `json`; add `from planner.kpi import step_trajectory, OracleSettings` and `from planner.trajectory import write_trajectory_csv`):

```python
def _setpoints_from_rec(rec: dict) -> Setpoints:
    s = rec["setpoints"]
    return Setpoints(s["crah_supply_air_temperature_c"],
                     s["crah_supply_air_mass_flow_rate_kg_s"],
                     s["chilled_water_supply_temperature_c"])


def run_prevalidation(recommendation_path: str, evaluator, baseline: Setpoints,
                      out_dir: str = "log/prevalidation", project_root: str = ".") -> dict:
    """Independently replay the RECOMMENDED setpoints (not the stored predicted_kpis)
    and compare against a baseline run. Emits report.md + trajectory_ai.csv into out_dir."""
    rec = json.loads(Path(recommendation_path).read_text())
    recommended = _setpoints_from_rec(rec)
    week_start = date.fromisoformat(rec["week_start"])
    forecast = _Forecast(week_start)

    # independent AI replay (+ trajectory if the evaluator can produce one)
    if hasattr(evaluator, "replay_with_trajectory"):
        ai_kpi, samples = evaluator.replay_with_trajectory(recommended, forecast)
        rows = step_trajectory(samples, hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    else:
        ai_kpi = evaluator.evaluate([recommended], forecast)[0]
        rows = []
    baseline_kpi = evaluator.evaluate([baseline], forecast)[0]

    metrics = validation_metrics(ai_kpi, baseline_kpi)
    report = render_report(metrics, plan_id=rec["plan_id"])
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "report.md").write_text(report)
    if rows:
        write_trajectory_csv(rows, str(Path(out_dir) / "trajectory_ai.csv"))
    return metrics


def run_prevalidation_with_oracle(recommendation_path: str, dt_engine_config: str,
                                  baseline: Setpoints, out_dir: str = "log/prevalidation",
                                  project_root: str = ".") -> dict:
    """Production wrapper: build the real ParallelEnvOracle and run an independent replay."""
    orc = ParallelEnvOracle(base_prototxt=dt_engine_config, project_root=project_root,
                            config=OracleConfig(n_workers=1, use_process_pool=False,
                                                log_root=str(Path(out_dir) / "oracle")))
    return run_prevalidation(recommendation_path, evaluator=orc, baseline=baseline,
                             out_dir=out_dir, project_root=project_root)
```

Keep the existing `set_status` function and the `_Forecast` helper class (both are defined ABOVE `run_prevalidation`; the replacement only touches `run_prevalidation` downward). Delete the now-unused `_kpi_from_predicted`. Add `step_trajectory` to the existing `from planner.kpi import OracleSettings` line.

Also update the `__main__` block at the bottom of the file so the CLI uses the production wrapper (the old block calls `run_prevalidation(args.recommendation, args.dt, baseline)` which no longer exists):
```python
    else:
        from planner.types import DEFAULT_SEARCH_SPACE as S
        baseline = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)   # coolest SAT/CHW, max flow
        run_prevalidation_with_oracle(args.recommendation, args.dt, baseline)
```

(`validation_metrics(ai, baseline)` and `render_report(metrics, plan_id)` already exist in `planner/validation.py` and take two `WeeklyKPI`; the flat metric keys are listed in the test above. The existing `tests/test_prevalidation_gate.py` only tests `set_status`, so the signature change does not break it.)

- [ ] **Step 5: Run the prevalidation test, verify pass**

Run: `$PY -m pytest tests/test_prevalidation_gate.py -v`
Expected: PASS.

- [ ] **Step 6: Fix the AI replay policy slot**

In `ai_trajectory_test.py:36`, change `policy="baseline"` to `policy="ai"`.

- [ ] **Step 7: Commit**

```bash
git add prevalidation.py planner/mock_evaluator.py ai_trajectory_test.py tests/test_prevalidation_gate.py
git commit -m "feat(dtwin): pre-validation is a real independent replay (+report +trajectory); fix policy=ai"
```

---

## Task 10: Auto-run pre-validation after planning (spec §4.2 wiring)

**Files:**
- Modify: `webapp/jobs.py` (`run_plan_job`)
- Test: covered by the Task 13 integration test (Docker); add a smoke assertion that the call is wired.

- [ ] **Step 1: Wire pre-validation into `run_plan_job`**

In `webapp/jobs.py::run_plan_job`, after `store.save_recommendation(plan_id, rec)` (line 148), append:

```python
    # independent pre-validation replay -> runs/<id>/{report.md, trajectory_ai.csv}
    try:
        from prevalidation import run_prevalidation_with_oracle
        from planner.types import DEFAULT_SEARCH_SPACE
        space = DEFAULT_SEARCH_SPACE
        baseline = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)  # coolest/max-flow
        run_prevalidation_with_oracle(str(plan_dir / "recommendation.json"), dt_cfg,
                                      baseline=baseline, out_dir=str(plan_dir / "prevalidation"))
    except Exception:  # noqa: BLE001 - pre-validation is advisory; never fail the plan on it
        logger.exception("prevalidation for %s failed", plan_id)
```

Add `from planner.types import Setpoints` to the lazy imports at the top of `run_plan_job` (next to the other `planner` imports).

- [ ] **Step 2: Sanity-check imports compile**

Run: `$PY -c "import webapp.jobs"`
Expected: no output (imports OK).

- [ ] **Step 3: Run the existing jobs + pipeline unit tests (no regressions)**

Run: `$PY -m pytest tests/test_jobs.py tests/test_pipeline.py -v`
Expected: PASS (these inject fake runners; the new code path is exercised by Task 13).

- [ ] **Step 4: Commit**

```bash
git add webapp/jobs.py
git commit -m "feat(dtwin): auto-run independent pre-validation after each plan"
```

---

## Task 11: Webapp safety — PATCH status-gate + KPI invalidation + approval block (spec §4.4)

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`. These reuse the existing `client` fixture and the `_op()` / `_ex()` header helpers already defined in that file (both return an `Authorization` header dict):

```python
_SP = {"crah_supply_air_temperature_c": 22.0,
       "crah_supply_air_mass_flow_rate_kg_s": 7.0,
       "chilled_water_supply_temperature_c": 15.0}


def test_patch_setpoints_rejected_after_approval(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"},
                      headers=_op()).json()["plan_id"]
    client.post(f"/api/plans/{pid}/approve", headers=_ex())          # -> approved
    r = client.patch(f"/api/plans/{pid}/setpoints", json=_SP, headers=_ex())
    assert r.status_code == 409


def test_patch_setpoints_invalidates_kpis_and_blocks_approval(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"},
                      headers=_op()).json()["plan_id"]
    client.patch(f"/api/plans/{pid}/setpoints", json=_SP, headers=_ex())
    rec = client.get(f"/api/plans/{pid}", headers=_ex()).json()["recommendation"]
    assert rec["predicted_kpis"] is None and rec.get("needs_revalidation") is True
    # approval is blocked until re-validation
    assert client.post(f"/api/plans/{pid}/approve", headers=_ex()).status_code == 409
```

- [ ] **Step 2: Run them, verify they fail**

Run: `$PY -m pytest tests/test_api.py -k "patch_setpoints" -v`
Expected: FAIL — PATCH currently has no status gate and never nulls KPIs.

- [ ] **Step 3: Gate + invalidate in `edit_setpoints`; block approval on `needs_revalidation`**

In `webapp/main.py`, replace `edit_setpoints` (lines 102-109) with:

```python
    @app.patch("/api/plans/{plan_id}/setpoints")
    def edit_setpoints(plan_id: str, edit: SetpointEdit, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        row = store.get_plan_row(plan_id)
        if rec is None or row is None:
            raise HTTPException(404, "no recommendation yet")
        if row["status"] not in (PlanStatus.PENDING_APPROVAL, PlanStatus.BLOCKED_UNSAFE):
            raise HTTPException(409, f"cannot edit setpoints from {row['status']!r}")
        rec["setpoints"] = edit.model_dump()
        # edited setpoints invalidate the stale prediction — force re-validation before approve
        rec["predicted_kpis"] = None
        rec["predicted_kpis_raw"] = None
        rec.pop("robust", None)
        rec["needs_revalidation"] = True
        store.save_recommendation(plan_id, rec)
        return rec["setpoints"]
```

And in `approve`, add the revalidation guard right after the `can_transition` check (line 72 area):
```python
        if rec.get("needs_revalidation"):
            raise HTTPException(409, "setpoints edited — re-validate before approving")
```

Ensure `PlanStatus` is imported (it already is, line 11).

- [ ] **Step 4: Run the api tests, verify pass**

Run: `$PY -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/main.py tests/test_api.py
git commit -m "feat(dtwin): PATCH setpoints status-gated + invalidates KPIs + blocks approval until re-validated"
```

---

## Task 12: Fail-closed auth (spec §4.4)

**Files:**
- Modify: `webapp/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:

```python
import pytest
from fastapi import HTTPException
from webapp.auth import TokenAuth


def test_no_tokens_fail_closed(monkeypatch):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)
    monkeypatch.delenv("DTWIN_INSECURE", raising=False)
    auth = TokenAuth.from_env()
    with pytest.raises(HTTPException) as e:
        auth.check(authorization=None, min_role="operator")
    assert e.value.status_code == 401


def test_insecure_opt_in_allows_all(monkeypatch):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)
    monkeypatch.setenv("DTWIN_INSECURE", "1")
    auth = TokenAuth.from_env()
    assert auth.check(authorization=None, min_role="expert") == "expert"
```

- [ ] **Step 2: Run them, verify they fail**

Run: `$PY -m pytest tests/test_auth.py -k "fail_closed or insecure" -v`
Expected: FAIL — current `check` returns `"expert"` when no tokens.

- [ ] **Step 3: Make `from_env`/`check` fail-closed**

In `webapp/auth.py`, add an `insecure` flag. Change `__init__` and `from_env`:

```python
    def __init__(self, tokens: dict[str, str], insecure: bool = False):
        self.tokens = tokens  # token -> role
        self.insecure = insecure

    @classmethod
    def from_env(cls) -> "TokenAuth":
        tokens = {}
        if os.environ.get("OPERATOR_TOKEN"):
            tokens[os.environ["OPERATOR_TOKEN"]] = "operator"
        if os.environ.get("EXPERT_TOKEN"):
            tokens[os.environ["EXPERT_TOKEN"]] = "expert"
        return cls(tokens, insecure=os.environ.get("DTWIN_INSECURE") == "1")
```

And change the top of `check`:

```python
    def check(self, authorization: Optional[str], min_role: str) -> str:
        if not self.tokens:
            # fail-closed: no tokens configured -> deny, unless DTWIN_INSECURE=1 dev opt-in
            if self.insecure:
                return "expert"
            raise HTTPException(status_code=401, detail="auth not configured")
        ...
```

- [ ] **Step 4: Run the auth tests, verify pass**

Run: `$PY -m pytest tests/test_auth.py -v`
Expected: PASS. `tests/test_api.py` always constructs `TokenAuth({...})` with explicit tokens, so it is unaffected. Any OTHER test that builds an app/auth with NO tokens and relied on the open default must now pass `auth=TokenAuth({}, insecure=True)`. Run `$PY -m pytest tests/test_public_api.py tests/test_jobs.py -v` and fix any such fixture.

- [ ] **Step 5: Commit**

```bash
git add webapp/auth.py tests/test_auth.py tests/test_api.py tests/test_public_api.py
git commit -m "feat(dtwin): fail-closed auth (no tokens -> deny unless DTWIN_INSECURE=1)"
```

---

## Task 13: Acceptance — the breach cannot ship (spec §4.5)

**Files:**
- Create: `tests/integration/test_fidelity_gate.py`
- Create: `docs/fidelity-acceptance.md`

- [ ] **Step 1: Write the Docker-gated regression test**

Create `tests/integration/test_fidelity_gate.py`:

```python
"""Docker-gated regression: the demonstrated 666-violation deployment cannot ship.
A plan that breaches on the perturbed plant must end either gated (blocked_unsafe /
deploy_blocked) or with a realized 0-violation deploy. Run:
  cd src && sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
    tests/integration/test_fidelity_gate.py -m integration -v"
"""
import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_breaching_plan_cannot_ship(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job, run_deploy_job, deploy_status_for
    from webapp.status import PlanStatus

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    plan_id = "gds-accept-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2}
    store.create_plan(plan_id, params["week_start"], params)

    run_plan_job(plan_id, params, store, lambda p: None)
    rec = store.get_recommendation(plan_id)

    if rec["status"] in (PlanStatus.BLOCKED_UNSAFE, PlanStatus.INFEASIBLE_FALLBACK):
        return  # gated at plan time — safe, breach cannot reach approval

    # otherwise it reached pending_approval: approve + deploy, assert the backstop holds
    rec["status"] = PlanStatus.APPROVED
    store.save_recommendation(plan_id, rec)
    store.set_status(plan_id, PlanStatus.APPROVED)
    store.set_status(plan_id, PlanStatus.DEPLOYING)
    run_deploy_job(plan_id, store, lambda p: None)

    realized = store.get_realized(plan_id)
    final = store.get_plan_row(plan_id)["status"]
    # EITHER the realized week is clean, OR the backstop blocked it — never silently 'deployed' with a breach
    assert final == deploy_status_for(realized)
    if realized["inlet_violation_steps"] > 0:
        assert final == PlanStatus.DEPLOY_BLOCKED
    else:
        assert final == PlanStatus.DEPLOYED
```

- [ ] **Step 2: Verify it is collected but deselected without Docker**

Run: `$PY -m pytest tests/integration/test_fidelity_gate.py -v`
Expected: `1 deselected` (the default `-m 'not integration'` filter skips it). No errors on collection.

- [ ] **Step 3: Run it under Docker (the real acceptance)**

Run:
```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_fidelity_gate.py -m integration -v"
```
Expected: PASS (may take several minutes — real EnergyPlus runs). If it fails because a breaching plan reached `deployed`, the gate is incomplete — debug Tasks 2/3 before proceeding.

- [ ] **Step 4: Record the realized acceptance result**

Create `docs/fidelity-acceptance.md` documenting: the command, the plan's status, and — if deployed — the **realized** `inlet_violation_steps` (must be 0) and energy vs baseline. This replaces the predicted-only "11.4% / 0 violations" claim with a realized one. Include the date and the git SHA.

- [ ] **Step 5: Run the FULL unit suite (no regressions)**

Run: `$PY -m pytest -v 2>&1 | tail -20`
Expected: all unit tests pass, 7 integration deselected (the prior 6 + the new one).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_fidelity_gate.py docs/fidelity-acceptance.md
git commit -m "test(dtwin): Docker regression — a breaching plan cannot ship; realized acceptance doc"
```

---

## Final verification

- [ ] Run the full unit suite: `$PY -m pytest -q` → green, 7 integration deselected.
- [ ] Run the Docker regression (Task 13 Step 3) → green.
- [ ] Confirm the demo artifact path is fixed: a fresh 1-day plan on a perturbed plant ends in `blocked_unsafe`/`deploy_blocked` OR realizes 0 violations — never `deployed` with a breach.
- [ ] Update memory (`dtwin-dual-loop-framework.md`) with the NOW-tier completion + the new statuses/schema 1.2.
