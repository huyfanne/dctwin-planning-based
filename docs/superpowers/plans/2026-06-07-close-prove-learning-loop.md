# Close & Prove the Learning Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make weekly plans safe-by-construction (a k·σ inlet pre-tighten auto-derived from calibration, applied to the inner search AND the robust gate), honestly settle the forecaster sub-loop (documented no-op seam), and prove the calibration loop converges over multiple weeks (a fast unit-level driver).

**Architecture:** A pure idempotent helper sets `ObjectiveWeights.inlet_forecast_margin = k·σ_inlet` (σ from calibration once weeks exist, else `SIGMA_PRIOR`); `run_weekly_plan` applies it to the search and `run_plan_job` applies it to the robust-rerank weights; the recommendation records it (schema 1.4). `refit_from_history` becomes an explicit no-op seam. A no-EnergyPlus N-week loop test proves convergence.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), pytest. No EnergyPlus, no frontend.

**Spec:** `docs/superpowers/specs/2026-06-07-close-prove-learning-loop-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`
- The sandbox strips a leading `cd` — prefix commands with `env -C <dir>`.
- Tests: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest <path> -v`
- Commit after each task (a `Co-Authored-By` trailer is appended by repo policy — keep it). Branch `feat/close-prove-learning-loop` (already created); do NOT switch branches.

---

## File map

| File | Change | Task |
|---|---|---|
| `planner/pipeline.py` | `K_SIGMA` + `apply_forecast_margin` helper; apply in `run_weekly_plan`; pass margin to `build_recommendation` | 1, 2, 4 |
| `webapp/jobs.py` | apply the margin to the robust-rerank weights in `run_plan_job` | 3 |
| `planner/recommendation.py` | top-level `inlet_forecast_margin`/`k_sigma` + schema 1.4 | 4 |
| `planner/history.py` | `refit_from_history` → documented no-op seam | 5 |
| `docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` | §9 erratum | 5 |
| `tests/test_loop_convergence.py` (new) | multi-week convergence proof | 6 |

---

## Task 1: `apply_forecast_margin` helper (spec §4.1, L1)

**Files:**
- Modify: `planner/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
from planner.pipeline import apply_forecast_margin, K_SIGMA
from planner.objective import ObjectiveWeights
from planner.calibrator import Calibration, SIGMA_PRIOR


def test_apply_forecast_margin_none_calibration_is_noop():
    w = ObjectiveWeights()
    assert apply_forecast_margin(w, None) is w   # unchanged object


def test_apply_forecast_margin_cold_start_uses_prior():
    cal = Calibration.identity()                 # n_weeks == 0
    w = apply_forecast_margin(ObjectiveWeights(), cal)
    assert w.inlet_forecast_margin == K_SIGMA * SIGMA_PRIOR["inlet_temp_max_c"]


def test_apply_forecast_margin_uses_sigma_when_weeks_exist():
    cal = Calibration(bias={"inlet_temp_max_c": 2.0}, sigma={"inlet_temp_max_c": 0.4},
                      n_weeks=3, version="weeks-3")
    w = apply_forecast_margin(ObjectiveWeights(), cal)
    assert abs(w.inlet_forecast_margin - K_SIGMA * 0.4) < 1e-9


def test_apply_forecast_margin_is_idempotent():
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.4}, n_weeks=3, version="weeks-3")
    w1 = apply_forecast_margin(ObjectiveWeights(), cal)
    w2 = apply_forecast_margin(w1, cal)          # applying twice == once (sets, not adds)
    assert w2.inlet_forecast_margin == w1.inlet_forecast_margin
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -k forecast_margin -v`
Expected: FAIL — `ImportError: cannot import name 'apply_forecast_margin'`.

- [ ] **Step 3: Implement the helper**

In `planner/pipeline.py`, add `import dataclasses` at the top and `from planner.calibrator import SIGMA_PRIOR` to the imports. Add after the imports (before `PlanRequest`):

```python
K_SIGMA = 1.0   # inlet pre-tighten = K_SIGMA * sigma_inlet (on by default)


def apply_forecast_margin(weights: "ObjectiveWeights", calibration,
                          k_sigma: float = K_SIGMA) -> "ObjectiveWeights":
    """Set inlet_forecast_margin = k * sigma_inlet so the search treats the inlet cap
    as (cap - margin). sigma comes from calibration once realized weeks exist, else the
    cold-start SIGMA_PRIOR. Idempotent (sets, never accumulates). calibration None -> unchanged."""
    if calibration is None:
        return weights
    sigma = (calibration.sigma_for("inlet_temp_max_c") if calibration.n_weeks > 0
             else SIGMA_PRIOR["inlet_temp_max_c"])
    return dataclasses.replace(weights, inlet_forecast_margin=k_sigma * sigma)
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -k forecast_margin -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/pipeline.py src/tests/test_pipeline.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): apply_forecast_margin helper — k*sigma inlet pre-tighten from calibration"
```

---

## Task 2: Apply the margin in `run_weekly_plan` (spec §4.1, L2)

**Files:**
- Modify: `planner/pipeline.py:60` (inside `run_weekly_plan`)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py`. `_FakeForecaster`, `MockEvaluator`, `MockSurface` are already imported at the top of that file; `K_SIGMA`, `apply_forecast_margin`, `Calibration` come from the import lines Task 1 added to this same file (Task 1 lands first — same file):

```python
def test_run_weekly_plan_applies_margin_from_calibration():
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.6}, n_weeks=2, version="weeks-2")
    captured = {}
    real_planner = None
    import planner.pipeline as pp

    class _SpyPlanner(pp.BeamPlanner):
        def __init__(self, space, evaluator, weights, *args, **kwargs):
            captured["margin"] = weights.inlet_forecast_margin
            super().__init__(space, evaluator, weights, *args, **kwargs)

    orig = pp.BeamPlanner
    pp.BeamPlanner = _SpyPlanner
    try:
        run_weekly_plan(
            PlanRequest(week_start=date(2013, 11, 11), days=7, grid=4, beam_width=3, levels=2),
            evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
            forecaster=_FakeForecaster(), calibration=cal)
    finally:
        pp.BeamPlanner = orig
    assert abs(captured["margin"] - K_SIGMA * 0.6) < 1e-9
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -k applies_margin -v`
Expected: FAIL — `captured["margin"]` is `0.0` (margin not yet applied).

- [ ] **Step 3: Apply the margin**

In `planner/pipeline.py::run_weekly_plan`, after `weights = weights or ObjectiveWeights()` (line 60), insert:

```python
    weights = apply_forecast_margin(weights, calibration)
```

(So the pre-tightened `weights` flow into both `validate_plan_request` — harmless, it only checks lambdas — and the `BeamPlanner`.)

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -v`
Expected: PASS. The existing pipeline tests pass `calibration=None` (or omit it), so `apply_forecast_margin` is a no-op for them — no regressions.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/pipeline.py src/tests/test_pipeline.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): run_weekly_plan pre-tightens the inner search by k*sigma (safe-by-construction)"
```

---

## Task 3: Apply the same margin to the robust rerank weights (spec §4.1, L3)

**Files:**
- Modify: `webapp/jobs.py` (`run_plan_job`, the `make_oracle_robust_rerank(...)` call)
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_robust_rerank_weights_carry_the_margin():
    from webapp.jobs import robust_weights_for
    from planner.calibrator import Calibration, SIGMA_PRIOR
    from planner.pipeline import K_SIGMA
    cal = Calibration(bias={}, sigma={"inlet_temp_max_c": 0.5}, n_weeks=2, version="weeks-2")
    w = robust_weights_for(cal)
    assert abs(w.inlet_forecast_margin - K_SIGMA * 0.5) < 1e-9
    # cold start uses the prior
    w0 = robust_weights_for(Calibration.identity())
    assert w0.inlet_forecast_margin == K_SIGMA * SIGMA_PRIOR["inlet_temp_max_c"]
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -k robust_rerank_weights -v`
Expected: FAIL — `ImportError: cannot import name 'robust_weights_for'`.

- [ ] **Step 3: Add the helper and use it in `run_plan_job`**

In `webapp/jobs.py`, add a module-level helper (near the top, after the imports):

```python
def robust_weights_for(calibration):
    """The margin-adjusted ObjectiveWeights for the robust rerank — same k*sigma
    pre-tighten the inner search uses, so the robust gate is consistent."""
    from planner.objective import ObjectiveWeights
    from planner.pipeline import apply_forecast_margin
    return apply_forecast_margin(ObjectiveWeights(), calibration)
```

Then in `run_plan_job`, change the `make_oracle_robust_rerank(...)` call's `weights=` argument from `ObjectiveWeights()` to `robust_weights_for(calibration)`:

```python
    robust_rerank_fn = make_oracle_robust_rerank(
        base_prototxt=dt_cfg,
        oracle_config=oracle.config,
        calibration=calibration,
        weights=robust_weights_for(calibration),
        n_scenarios=int(params.get("n_scenarios", 4)),
        log_root=str(plan_dir / "robust"),
    )
```

(`calibration` is already in scope — `run_plan_job` does `calibration = load_calibration("data/calibration.json")` just above.) After this change the lazy `from planner.objective import ObjectiveWeights` import inside `run_plan_job` is unused — remove that one line (it now lives only inside `robust_weights_for`).

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/jobs.py src/tests/test_jobs.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): robust rerank uses the same k*sigma margin as the search (consistent gate)"
```

---

## Task 4: Record the margin in the recommendation — schema 1.4 (spec §4.1/§5, L4)

**Files:**
- Modify: `planner/recommendation.py`
- Modify: `planner/pipeline.py` (the `build_recommendation(...)` call)
- Test: `tests/test_recommendation.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing recommendation test**

Append to `tests/test_recommendation.py`:

```python
def test_build_recommendation_records_margin_schema_1_4():
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from datetime import date
    kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                    inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(
        setpoints=Setpoints(22.0, 7.0, 15.0), kpi=kpi, week_start=date(2013, 11, 11),
        days=7, forecast_method="persistence", search_meta={"evals": 1},
        inlet_forecast_margin=0.6, k_sigma=1.0)
    assert rec["schema_version"] == "1.4"
    assert rec["inlet_forecast_margin"] == 0.6
    assert rec["k_sigma"] == 1.0
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py -k records_margin -v`
Expected: FAIL — `build_recommendation()` has no `inlet_forecast_margin` kwarg.

- [ ] **Step 3: Add the params + top-level fields**

In `planner/recommendation.py`, add to the `build_recommendation` signature (after `forecast_meta`):

```python
    forecast_meta: Optional[dict] = None,
    inlet_forecast_margin: Optional[float] = None,
    k_sigma: Optional[float] = None,
) -> dict:
```

And after the `forecast_meta` schema-1.3 block (just before `return rec`), insert:

```python
    if inlet_forecast_margin is not None:
        rec["inlet_forecast_margin"] = inlet_forecast_margin
        rec["k_sigma"] = k_sigma
        rec["schema_version"] = "1.4"
```

- [ ] **Step 4: Pass them from the pipeline**

In `planner/pipeline.py::run_weekly_plan`, add to the `build_recommendation(...)` call (after `forecast_meta=forecast_meta,`):

```python
        inlet_forecast_margin=weights.inlet_forecast_margin,
        k_sigma=K_SIGMA,
```

(`weights` here is the margin-adjusted weights from Task 2; `weights.inlet_forecast_margin` is `0.0` when there's no calibration, which still records the field and bumps to 1.4 — that's intended.)

- [ ] **Step 5: Run tests, verify pass + update existing schema assertions**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py tests/test_pipeline.py -v`
Expected: PASS for the new test. NOTE: `run_weekly_plan` now always passes `inlet_forecast_margin` (0.0 when no calibration), so every recommendation it builds is `schema_version "1.4"`. Update any `tests/test_pipeline.py` assertion that pinned `"1.3"` to `"1.4"`. The `tests/test_recommendation.py` cases that call `build_recommendation` WITHOUT `inlet_forecast_margin` keep their lower schema (1.0–1.3) and are unaffected.

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/recommendation.py src/planner/pipeline.py src/tests/test_recommendation.py src/tests/test_pipeline.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): record inlet_forecast_margin + k_sigma in recommendation (schema 1.4)"
```

---

## Task 5: Forecaster sub-loop honest no-op seam (spec §4.2, L5)

**Files:**
- Modify: `planner/history.py:32-40` (`refit_from_history`)
- Modify: `docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` (§9 erratum)
- Test: `tests/test_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_history.py`:

```python
def test_refit_from_history_is_documented_noop(tmp_path, monkeypatch):
    import runpy
    from planner.history import refit_from_history
    called = {"ran": False}
    monkeypatch.setattr(runpy, "run_path", lambda *a, **k: called.__setitem__("ran", True))
    assert refit_from_history() is None          # returns None
    assert called["ran"] is False                # does NOT re-run fit_forecaster
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_history.py -k documented_noop -v`
Expected: FAIL — the current `refit_from_history` calls `runpy.run_path(...)`, so `called["ran"]` is True.

- [ ] **Step 3: Make it a documented no-op seam**

In `planner/history.py`, replace `refit_from_history` (lines 32-40) with:

```python
def refit_from_history(forecaster_pkl: str = "models/forecaster.pkl") -> None:
    """Documented NO-OP seam (sim-only v1).

    In sim-only mode the realized IT-load EQUALS the forecast we injected (the
    perturbed plant degrades cooling, not load), and the realized record is
    aggregate weekly KPIs — schema-incompatible with the forecaster's per-step
    IT-load CSV. So there is no forecaster feedback to apply: the realized-feedback
    path is the CALIBRATION loop (advance_calibration -> recompute_calibration ->
    corrected objective). This seam activates only with real per-step telemetry
    (parked with the BMS/telemetry work). Mirrors planner.recalibrator.recalibrate.
    Do not delete."""
    return None
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_history.py -v`
Expected: PASS.

- [ ] **Step 5: Add the §9 erratum**

In `docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md`, find the §9 line that says realized System Data feeds the next week's forecaster (the `deploy.py` / loop-closure bullet) and append this erratum note immediately after that bullet:

```markdown
> **Erratum (2026-06-07, LATER sub-project A):** in sim-only v1 the realized load equals the injected
> forecast, so the realized-feedback path is the **calibration** loop (output-residual bias/σ → corrected
> objective), not the forecaster. `refit_from_history` is a documented no-op seam that activates only with
> real per-step telemetry. See `2026-06-07-close-prove-learning-loop-design.md` §4.2.
```

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/history.py src/tests/test_history.py docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "docs(dtwin): forecaster sub-loop is a documented no-op seam in sim-only (calibration is the feedback) + §9 erratum"
```

---

## Task 6: Multi-week convergence proof (spec §4.3, L6)

**Files:**
- Create: `tests/test_loop_convergence.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_loop_convergence.py`:

```python
"""Prove the calibration learning loop converges over N weeks with NO EnergyPlus.

Twin = MockEvaluator(MockSurface(inlet_base=20)) — energy-optimum inlet ~24.7 C (near the
26 C cap). Plant = the same surface shifted +2 C (MockSurface(inlet_base=22)) — a fixed +2 C
realized inlet bias. (+2 C is below the NOW-tier RESIDUAL_CLIP of 3 C, so calibration can
LEARN it fully; the twin opt at ~24.7 C means +2 C breaches week 1.) Each week: plan on the
twin (with the k*sigma pre-tighten + the learned calibration) -> 'deploy' on the plant ->
learn (advance_calibration on RAW predicted vs realized -> recompute_calibration) -> re-plan.
"""
from datetime import date

from planner.pipeline import run_weekly_plan, PlanRequest
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.calibrator import Calibration, recompute_calibration
from planner.history import advance_calibration
from planner.types import Setpoints


class _FakeForecaster:
    method = "persistence"
    def forecast(self, week_start, n_steps):
        class _F:
            week_start = date(2013, 11, 11)
            method = "persistence"
            def materialize(self, root): pass
        return _F()


def _sp(rec):
    s = rec["setpoints"]
    return Setpoints(s["crah_supply_air_temperature_c"],
                     s["crah_supply_air_mass_flow_rate_kg_s"],
                     s["chilled_water_supply_temperature_c"])


def test_multi_week_loop_converges(tmp_path):
    twin = MockEvaluator(MockSurface(inlet_base=20.0))       # predicts inlet x (opt ~24.7 C)
    plant = MockEvaluator(MockSurface(inlet_base=22.0))      # realizes inlet x + 2
    histp = str(tmp_path / "calibration_history.json")
    calp = str(tmp_path / "calibration.json")
    cal = Calibration.identity()

    sigmas, biases, realized_violations = [], [], []
    for wk in range(4):
        rec = run_weekly_plan(
            PlanRequest(week_start=date(2013, 11, 4 + wk), days=1, grid=4, beam_width=3, levels=2),
            evaluator=twin, forecaster=_FakeForecaster(), calibration=cal)
        rk = plant.evaluate([_sp(rec)])[0]                    # 'deploy' on the plant
        realized = {"total_hvac_energy_kwh": rk.total_hvac_energy_kwh,
                    "pue_mean": rk.pue_mean, "inlet_temp_max_c": rk.inlet_temp_max}
        # learn from RAW predicted (uncalibrated) vs realized
        advance_calibration(rec["predicted_kpis_raw"], realized, date(2013, 11, 4 + wk), histp)
        cal = recompute_calibration(histp, calp)
        sigmas.append(cal.sigma["inlet_temp_max_c"])
        biases.append(cal.bias["inlet_temp_max_c"])
        realized_violations.append(rk.inlet_violation_steps)

    assert realized_violations[0] > 0                         # week 1 breaches (nothing learned yet)
    assert all(v == 0 for v in realized_violations[1:])       # feasible once the bias is learned
    assert sigmas == sorted(sigmas, reverse=True)             # sigma non-increasing (converges)
    assert abs(biases[-1] - biases[-2]) < 1e-6                # bias stabilized (fixed +2 C)
    assert abs(biases[-1] - 2.0) < 0.5                        # learned ~the true +2 C plant bias
```

- [ ] **Step 2: Run it, verify it passes (the loop logic already exists after Tasks 1-4)**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_loop_convergence.py -v`
Expected: PASS. If `realized_violations[0]` is 0 (week 1 unexpectedly feasible), confirm the twin's energy-optimum inlet ≈ 24.7 °C (`MockSurface(inlet_base=20)`, opt at sat=24/flow=8/chwst=17 → `20 + 4 + 2 − 1.28 = 24.72`) so realized `24.72 + 2 = 26.72 > 26`. If `sigmas` is not monotone, confirm the NOW-tier fading-floor `fit_calibration` (`σ = max(sample, prior/n)`) and `RESIDUAL_CLIP["inlet_temp_max_c"] == 3.0` (so the +2 °C residual is NOT clipped) are in `planner/calibrator.py`.

- [ ] **Step 3: Run the full unit suite (no regressions)**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`
Expected: all unit pass; integration tests deselected.

- [ ] **Step 4: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/tests/test_loop_convergence.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "test(dtwin): multi-week loop convergence proof (sigma shrinks, bias stabilizes, plans become feasible)"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Confirm a fresh plan with a populated calibration carries `inlet_forecast_margin > 0` and `schema_version "1.4"`.
- [ ] Update memory (`dtwin-dual-loop-framework.md`) with LATER sub-project A (k·σ pre-tighten on by default, forecaster no-op seam, convergence proof, schema 1.4).
