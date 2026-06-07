# NEXT Tier — Visibility + Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the recommended plan's per-step inlet/power/PUE trajectory (nominal + worst-case scenario) visible to operators before approval, show a predicted-vs-realized History trend, and harden the engine (startup fail-fast, real-weather pkl + honest forecast labels, robust scenario error-handling, container teardown).

**Architecture:** A real `ParallelEnvOracle.replay_with_trajectory` feeds pre-validation, which replays the winner on the nominal twin AND the deterministic max-perturbation plant, emitting two trajectory CSVs served by `GET /api/plans/{id}/trajectory`. Frontend Recharts line charts overlay them with the 26 °C cap. Backend hardening is independent per-subsystem.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), pytest, FastAPI; React 19 + Vite + Recharts + vitest; dctwin/EnergyPlus 9.5 via Docker (integration only).

**Spec:** `docs/superpowers/specs/2026-06-07-next-tier-visibility-hardening-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`
- Run Python from `/mnt/lv/home/hoanghuy/newcode/dctwin/src`; run `npm` from `/mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend`.
- The sandbox strips a leading `cd`; prefix shell commands with `env -C <dir>` instead (e.g. `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest ...`).
- Unit tests: `$PY -m pytest <path> -v` (default `-m 'not integration'` applies).
- Commit after each task. Branch `feat/next-tier-visibility-hardening` (already created).

---

## File map

| File | Change | Task |
|---|---|---|
| `planner/pipeline.py` | `validate_plan_request` + call at top of `run_weekly_plan`; pass `forecast_meta` | 1, 7 |
| `webapp/main.py` | `create_plan` → 422 on ValueError; `GET /trajectory` | 1, 4 |
| `planner/oracle_worker.py` | `run_episode_with_samples`, `evaluate_one_with_samples`; container teardown | 2, 10 |
| `planner/oracle.py` | `ParallelEnvOracle.replay_with_trajectory` | 2 |
| `prevalidation.py` | worst-case replay → `trajectory_worst.csv` | 3 |
| `webapp/store.py` | `get_trajectory`; `realized_energy_kwh` column | 4, 5 |
| `frontend/src/api.ts` | `getTrajectory`, `TrajRow`, `PlanSummary.realized_energy_kwh` | 6 |
| `frontend/src/pages/Review.tsx` | trajectory line chart | 6 |
| `frontend/src/pages/History.tsx` | predicted-vs-realized trend chart | 6 |
| `planner/recommendation.py` | `forecast_meta` + schema 1.3 | 7 |
| `planner/objective.py` | `ObjectiveWeights.inlet_forecast_margin` + `is_feasible` gate | 8 |
| `planner/robust.py` | scenario try/except + ⌈N/2⌉ rule + `scenarios_ok` | 9 |
| `tests/integration/test_trajectory_emit.py` (new) | Docker acceptance | 11 |

---

## Task 1: Startup fail-fast — `validate_plan_request` (spec §4.2, N1)

**Files:**
- Modify: `planner/pipeline.py`
- Modify: `webapp/main.py:36-46`
- Test: `tests/test_pipeline.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
import pytest
from planner.pipeline import validate_plan_request, PlanRequest
from planner.beam_search import BeamConfig
from planner.objective import ObjectiveWeights


def test_validate_plan_request_accepts_defaults():
    validate_plan_request(PlanRequest(week_start=date(2013, 11, 11)),
                          ObjectiveWeights(), BeamConfig())  # no raise


@pytest.mark.parametrize("beam,weights,days,msg", [
    (BeamConfig(grid=1), ObjectiveWeights(), 7, "grid"),
    (BeamConfig(beam_width=0), ObjectiveWeights(), 7, "beam_width"),
    (BeamConfig(levels=-1), ObjectiveWeights(), 7, "levels"),
    (BeamConfig(max_evals=0), ObjectiveWeights(), 7, "max_evals"),
    (BeamConfig(), ObjectiveWeights(lambda_temp=-1.0), 7, "weight"),
    (BeamConfig(), ObjectiveWeights(), 0, "days"),
])
def test_validate_plan_request_rejects(beam, weights, days, msg):
    with pytest.raises(ValueError, match=msg):
        validate_plan_request(PlanRequest(week_start=date(2013, 11, 11), days=days), weights, beam)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -k validate_plan_request -v`
Expected: FAIL — `ImportError: cannot import name 'validate_plan_request'`.

- [ ] **Step 3: Implement `validate_plan_request` and call it**

In `planner/pipeline.py`, add after the imports (the `BeamConfig`/`ObjectiveWeights` imports already exist):

```python
def validate_plan_request(request: "PlanRequest", weights: ObjectiveWeights,
                          beam: BeamConfig) -> None:
    """Fail-fast BEFORE any EnergyPlus run (spec §11). Raises ValueError on a
    misconfigured request so a bad plan never launches hundreds of Docker runs."""
    if beam.grid < 2:
        raise ValueError(f"grid must be >= 2, got {beam.grid}")
    if beam.beam_width < 1:
        raise ValueError(f"beam_width must be >= 1, got {beam.beam_width}")
    if beam.levels < 0:
        raise ValueError(f"levels must be >= 0, got {beam.levels}")
    if beam.max_evals <= 0:
        raise ValueError(f"max_evals must be > 0, got {beam.max_evals}")
    if request.days < 1:
        raise ValueError(f"days must be >= 1, got {request.days}")
    for name in ("lambda_temp", "lambda_rh", "lambda_zone"):
        v = getattr(weights, name)
        if v < 0:
            raise ValueError(f"objective weight {name} must be >= 0, got {v}")
```

Then in `run_weekly_plan`, immediately after `beam = BeamConfig(...)` (line 41), insert:

```python
    validate_plan_request(request, weights, beam)
```

(Note: broadcast-dim==45 is structurally enforced already — `env_actions.action_spec_from_actions` raises `ValueError("No AGENT_CONTROLLED actions found in env")` if the env exposes none, before any episode.)

- [ ] **Step 4: Run the pipeline tests, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_pipeline.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Validate SYNCHRONOUSLY in `create_plan` → 422**

The background worker swallows exceptions (`jobs.py:71` marks the plan `failed`), so wrapping `submit()` would never surface a 422. Validate at POST time instead. In `webapp/main.py::create_plan` (lines 37-46), replace the whole function body with:

```python
    @app.post("/api/plans", response_model=PlanCreated, status_code=202)
    def create_plan(params: PlanParams, role: str = Depends(operator)):
        from datetime import date as _date
        from planner.pipeline import PlanRequest, validate_plan_request
        from planner.beam_search import BeamConfig
        from planner.objective import ObjectiveWeights
        p = params.model_dump()

        def _v(key, default):  # keep an explicit 0 (invalid), default only on None/missing
            x = p.get(key)
            return default if x is None else int(x)

        try:
            validate_plan_request(
                PlanRequest(week_start=_date.fromisoformat(p["week_start"]), days=_v("days", 7)),
                ObjectiveWeights(),
                BeamConfig(grid=_v("grid", 5), beam_width=_v("beam_width", 5), levels=_v("levels", 3)))
        except ValueError as e:
            raise HTTPException(422, str(e))

        plan_id = f"gds-{params.week_start}-{uuid.uuid4().hex[:6]}"
        store.create_plan(plan_id, params.week_start, p)
        if run_sync:
            job_runner.runner(plan_id, p, store, lambda pr: store.write_progress(plan_id, pr))
        else:
            job_runner.submit(plan_id, p)
        return PlanCreated(plan_id=plan_id, status="queued")
```

(`planner.pipeline`/`beam_search`/`objective` are pure — no dctwin import — so importing them in the route is safe.)

- [ ] **Step 6: Write + run the API test (real 422)**

Append to `tests/test_api.py` (reuses the `client` fixture + `_op()`):

```python
def test_create_plan_rejects_bad_grid(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11", "grid": 1}, headers=_op())
    assert r.status_code == 422
    assert "grid" in r.json()["detail"]


def test_create_plan_accepts_valid(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11", "grid": 5}, headers=_op())
    assert r.status_code == 202
```

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -v`
Expected: PASS. (If `PlanParams` already constrains `grid` via pydantic, the bad-grid request still 422s — at the validation layer — so the test holds either way.)

- [ ] **Step 7: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/pipeline.py src/webapp/main.py src/tests/test_pipeline.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): startup fail-fast validate_plan_request (+422 wiring)"
```

---

## Task 2: Real per-step trajectory capture in the oracle (spec §4.1 A1, N2)

**Files:**
- Modify: `planner/oracle_worker.py`
- Modify: `planner/oracle.py`
- Test: `tests/test_oracle_worker.py`, `tests/test_oracle.py`

- [ ] **Step 1: Write the failing test for `run_episode_with_samples`**

Append to `tests/test_oracle_worker.py`. **Reuse** the file's existing module-level `_FakeEnv(traces, n_steps)` + `_FakeUnwrapped(traces)` fixtures (lines 10-40) — do NOT define new classes with those names (that would shadow the existing ones and break the other two tests). The existing `_FakeEnv` is trace-driven: `traces[obs_name][step]`, `reset()`→step 0, each `step()`→advance:

```python
def test_run_episode_with_samples_returns_kpi_and_per_step():
    from planner.oracle_worker import run_episode_with_samples
    # reset sample (step 0) + 8 stepped samples -> indices 0..8 read, so 10 values is safe
    traces = {"total power": [1200.0] * 10, "total it power": [1000.0] * 10,
              "inlet_a": [24.0] * 10}
    env = _FakeEnv(traces, n_steps=9)
    mon = MonitorSpec(total_power_name="total power", it_power_name="total it power",
                      inlet_temp_names=["inlet_a"], inlet_rh_names=[], zone_temp_names=[])
    kpi, samples = run_episode_with_samples(env, np.zeros(3), mon,
                                            hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    assert kpi.feasible
    assert len(samples) == 9              # reset sample + 8 in-loop samples
    assert samples[0].inlet_temps == [24.0]
```

(`MonitorSpec` is a dataclass `(total_power_name, it_power_name, inlet_temp_names, inlet_rh_names, zone_temp_names)` — `planner/monitor.py:6-12`. `np`/`MonitorSpec`/`OracleSettings` are already imported at the top of the file.)

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle_worker.py -k with_samples -v`
Expected: FAIL — `ImportError: cannot import name 'run_episode_with_samples'`.

- [ ] **Step 3: Add `run_episode_with_samples` + `evaluate_one_with_samples`**

In `planner/oracle_worker.py`, refactor `run_episode` to delegate to a sample-returning core. Replace the existing `run_episode` (lines 41-52) with:

```python
def run_episode_with_samples(env, action: np.ndarray, monitor: MonitorSpec,
                             hours_per_step: float, settings: OracleSettings):
    """Like run_episode but also returns the per-step StepSample list."""
    samples: list[StepSample] = []
    env.reset()
    samples.append(read_step_sample(env.unwrapped, monitor))
    done = False
    while not done:
        _obs, _rew, done, _trunc, _info = env.step(action)
        if not done:
            samples.append(read_step_sample(env.unwrapped, monitor))
    return aggregate_kpi(samples, hours_per_step, settings), samples


def run_episode(env, action: np.ndarray, monitor: MonitorSpec,
                hours_per_step: float, settings: OracleSettings) -> WeeklyKPI:
    """Step a (already-built) env to completion with a fixed action; aggregate KPI."""
    kpi, _samples = run_episode_with_samples(env, action, monitor, hours_per_step, settings)
    return kpi
```

Then add a sample-returning worker (mirror `evaluate_one`, lines 63-103, but return the samples). Add after `evaluate_one`:

```python
def evaluate_one_with_samples(task: EvalTask):
    """Like evaluate_one but returns (WeeklyKPI, list[StepSample]). For the inline
    trajectory replay only (never the process pool). Returns (_infeasible(), []) on failure."""
    import dctwin
    from dctwin.utils import config as dt_config
    from planner.env_actions import mapper_from_env
    from planner.monitor import discover_monitor
    import dctwin.third_parties.eplus.core as _eplus_core
    _eplus_core.EplusBackendMixin._post_process = staticmethod(lambda: None)

    env = None
    try:
        dt_config.set_log_dir(task.log_dir)
        env = dctwin.make_env(env_proto_config=task.week_config_path, reward_fn=lambda x: 0)
        backend = getattr(getattr(env, "unwrapped", env), "eplus_backend", None)
        if backend is not None and task.bcvtb_host:
            backend._host = task.bcvtb_host
        broadcaster = mapper_from_env(env)
        monitor = discover_monitor(env, hall=task.monitored_hall)
        action = broadcaster.expand(Setpoints(*task.candidate))
        return run_episode_with_samples(env, action, monitor, task.hours_per_step,
                                        OracleSettings(**task.settings_kwargs))
    except Exception as exc:  # noqa: BLE001
        logger.warning("trajectory candidate %s failed: %s", task.candidate, exc)
        return _infeasible(str(exc)), []
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
```

- [ ] **Step 4: Add `ParallelEnvOracle.replay_with_trajectory`**

In `planner/oracle.py`, add an injectable sample-worker to `__init__` and the replay method. Change `__init__` (lines 43-48) to also store a sample worker:

```python
    def __init__(self, base_prototxt: str, config: Optional[OracleConfig] = None,
                 project_root: str = ".", worker_fn=None, sample_worker_fn=None):
        self.base_prototxt = base_prototxt
        self.config = config or OracleConfig()
        self.project_root = project_root
        self._worker = worker_fn if worker_fn is not None else evaluate_one
        self._sample_worker = sample_worker_fn
```

Add this import near the top (`evaluate_one` is already imported from oracle_worker): change line 9 to
`from planner.oracle_worker import EvalTask, evaluate_one, evaluate_one_with_samples`.

Then add the method (after `evaluate`):

```python
    def replay_with_trajectory(self, setpoints: Setpoints, forecast: Optional[Any] = None):
        """Inline single-candidate run that ALSO returns the per-step StepSample list.
        Used by pre-validation to emit a trajectory CSV (never the process pool)."""
        cfg = self.config
        hours_per_step = 1.0 / cfg.timesteps_per_hour
        if forecast is not None and hasattr(forecast, "materialize"):
            forecast.materialize(self.project_root)
        log_root = Path(cfg.log_root).resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        if forecast is not None and getattr(forecast, "week_start", None) is not None:
            week_cfg_path = str(log_root / "week.prototxt")
            self._write_week_cfg(forecast, week_cfg_path)
        else:
            week_cfg_path = str(Path(self.base_prototxt).resolve())
        task = EvalTask(
            candidate=setpoints.as_tuple(), week_config_path=week_cfg_path,
            log_dir=str(log_root / "replay"), hours_per_step=hours_per_step,
            settings_kwargs=cfg.settings.__dict__, bcvtb_host=cfg.bcvtb_host,
            monitored_hall=cfg.monitored_hall)
        worker = self._sample_worker or evaluate_one_with_samples
        return worker(task)
```

- [ ] **Step 5: Write + run the oracle test (injected sample worker)**

Append to `tests/test_oracle.py`:

```python
def test_replay_with_trajectory_uses_sample_worker():
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.types import Setpoints, WeeklyKPI
    from planner.kpi import StepSample
    calls = {}
    fake_kpi = WeeklyKPI(total_hvac_energy_kwh=10.0, pue_mean=1.2, inlet_temp_max=24.0,
                         inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    fake_samples = [StepSample(total_power_w=1200.0, it_power_w=1000.0, inlet_temps=[24.0])]

    def fake_sample_worker(task):
        calls["candidate"] = task.candidate
        return fake_kpi, fake_samples

    orc = ParallelEnvOracle(base_prototxt="configs/dt/dt.prototxt",
                            config=OracleConfig(use_process_pool=False, log_root="log/test_replay"),
                            sample_worker_fn=fake_sample_worker)
    kpi, samples = orc.replay_with_trajectory(Setpoints(22.0, 7.0, 15.0), forecast=None)
    assert kpi is fake_kpi and samples is fake_samples
    assert calls["candidate"] == (22.0, 7.0, 15.0)
```

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle.py tests/test_oracle_worker.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/oracle_worker.py src/planner/oracle.py src/tests/test_oracle_worker.py src/tests/test_oracle.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): real per-step trajectory capture (ParallelEnvOracle.replay_with_trajectory)"
```

---

## Task 3: Pre-validation worst-case replay (spec §4.1 A2, N3)

**Files:**
- Modify: `prevalidation.py`
- Test: `tests/test_prevalidation_gate.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prevalidation_gate.py`:

```python
def test_run_prevalidation_emits_worst_trajectory(tmp_path):
    import json
    from datetime import date
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from planner.mock_evaluator import MockEvaluator, MockSurface
    import prevalidation

    kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                    inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(setpoints=Setpoints(22.0, 7.0, 15.0), kpi=kpi,
                               week_start=date(2013, 11, 11), days=1, forecast_method="persistence",
                               search_meta={"evals": 1})
    rec_path = tmp_path / "recommendation.json"
    rec_path.write_text(json.dumps(rec))

    nominal = MockEvaluator(MockSurface(inlet_cap=999.0))
    worst = MockEvaluator(MockSurface(inlet_cap=999.0))
    prevalidation.run_prevalidation(str(rec_path), evaluator=nominal,
                                    baseline=Setpoints(24.0, 13.8, 13.0),
                                    out_dir=str(tmp_path), worst_evaluator=worst)
    assert (tmp_path / "trajectory_ai.csv").exists()
    assert (tmp_path / "trajectory_worst.csv").exists()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_prevalidation_gate.py -k worst_trajectory -v`
Expected: FAIL — `run_prevalidation()` has no `worst_evaluator` kwarg.

- [ ] **Step 3: Add `worst_evaluator` to `run_prevalidation` + build the worst oracle in the wrapper**

In `prevalidation.py`, change `run_prevalidation`'s signature to add `worst_evaluator=None` and, after writing `trajectory_ai.csv`, replay on the worst evaluator. Locate the block that writes the ai trajectory (`if rows:` writing `trajectory_ai.csv`) and add directly after it:

```python
    if worst_evaluator is not None and hasattr(worst_evaluator, "replay_with_trajectory"):
        _wk, wsamples = worst_evaluator.replay_with_trajectory(recommended, forecast)
        wrows = step_trajectory(wsamples, hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
        if wrows:
            write_trajectory_csv(wrows, str(Path(out_dir) / "trajectory_worst.csv"))
```

(Ensure the signature line reads `def run_prevalidation(recommendation_path, evaluator, baseline, out_dir="log/prevalidation", project_root=".", worst_evaluator=None):`.)

In `run_prevalidation_with_oracle`, build the max-perturbation worst oracle and pass it. Replace its body's oracle construction so it builds both the nominal oracle and a worst-case oracle:

```python
def run_prevalidation_with_oracle(recommendation_path: str, dt_engine_config: str,
                                  baseline: Setpoints, out_dir: str = "log/prevalidation",
                                  project_root: str = ".") -> dict:
    """Production wrapper: nominal replay + the deterministic max-perturbation scenario replay."""
    from pathlib import Path
    from planner.calibrator import load_calibration
    from planner.plant import DEFAULT_PLANT, build_plant_prototxt
    from planner.robust import make_scenarios, scenario_spread

    nominal = ParallelEnvOracle(base_prototxt=dt_engine_config, project_root=project_root,
                                config=OracleConfig(n_workers=1, use_process_pool=False,
                                                    log_root=str(Path(out_dir) / "oracle")))
    spread = scenario_spread(load_calibration("data/calibration.json"))
    # make_scenarios scales the (degrading, <1) DEFAULT_PLANT factors by m in [1-spread, 1+spread];
    # index [0] is the SMALLEST m -> most-degraded -> HOTTEST plant. ([-1] would be the coolest.)
    worst_plant = make_scenarios(DEFAULT_PLANT, 4, spread)[0]   # hottest (most-degraded) scenario
    worst_proto = build_plant_prototxt(dt_engine_config, worst_plant, str(Path(out_dir) / "worst"))
    worst = ParallelEnvOracle(base_prototxt=worst_proto, project_root=project_root,
                              config=OracleConfig(n_workers=1, use_process_pool=False,
                                                  log_root=str(Path(out_dir) / "worst" / "oracle")))
    return run_prevalidation(recommendation_path, evaluator=nominal, baseline=baseline,
                             out_dir=out_dir, project_root=project_root, worst_evaluator=worst)
```

(`MockEvaluator` must expose `replay_with_trajectory` — it already does from the NOW tier; the test relies on it.)

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_prevalidation_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/prevalidation.py src/tests/test_prevalidation_gate.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): pre-validation also replays the worst-case scenario (trajectory_worst.csv)"
```

---

## Task 4: `GET /api/plans/{id}/trajectory` (spec §4.1 A3 backend, N4)

**Files:**
- Modify: `webapp/store.py`
- Modify: `webapp/main.py`
- Test: `tests/test_store.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing store test**

Append to `tests/test_store.py`:

```python
def test_get_trajectory_parses_two_csvs(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    pdir = store.plan_dir("p1") / "prevalidation"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "trajectory_ai.csv").write_text("step,inlet_temp_max_c,hvac_power_kw,pue\n0,24.0,0.2,1.2\n")
    (pdir / "trajectory_worst.csv").write_text("step,inlet_temp_max_c,hvac_power_kw,pue\n0,28.0,0.5,1.3\n")
    traj = store.get_trajectory("p1")
    assert traj["nominal"][0]["inlet_temp_max_c"] == 24.0
    assert traj["worst"][0]["inlet_temp_max_c"] == 28.0


def test_get_trajectory_missing_is_empty(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.plan_dir("p2")
    assert store.get_trajectory("p2") == {"nominal": [], "worst": []}
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_store.py -k trajectory -v`
Expected: FAIL — `PlanStore` has no `get_trajectory`.

- [ ] **Step 3: Add `get_trajectory` to `PlanStore`**

In `webapp/store.py`, add (uses `csv` + `Path`; add `import csv` at the top):

```python
    def _read_traj_csv(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open() as f:
            for r in csv.DictReader(f):
                rows.append({
                    "step": int(r["step"]),
                    "inlet_temp_max_c": None if r["inlet_temp_max_c"] == "" else float(r["inlet_temp_max_c"]),
                    "hvac_power_kw": None if r["hvac_power_kw"] == "" else float(r["hvac_power_kw"]),
                    "pue": None if r["pue"] == "" else float(r["pue"]),
                })
        return rows

    def get_trajectory(self, plan_id: str) -> dict:
        pdir = self.plan_dir(plan_id) / "prevalidation"
        return {"nominal": self._read_traj_csv(pdir / "trajectory_ai.csv"),
                "worst": self._read_traj_csv(pdir / "trajectory_worst.csv")}
```

- [ ] **Step 4: Add the endpoint**

In `webapp/main.py`, add after `get_progress` (line 63):

```python
    @app.get("/api/plans/{plan_id}/trajectory")
    def get_trajectory(plan_id: str, role: str = Depends(operator)):
        if store.get_plan_row(plan_id) is None:
            raise HTTPException(404, "plan not found")
        return store.get_trajectory(plan_id)
```

- [ ] **Step 5: Write + run the API test**

Append to `tests/test_api.py`:

```python
def test_get_trajectory_endpoint(client):
    from webapp.store import PlanStore  # noqa: F401
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    r = client.get(f"/api/plans/{pid}/trajectory", headers=_op())
    assert r.status_code == 200
    body = r.json()
    assert "nominal" in body and "worst" in body  # empty until a real run emits CSVs
```

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_store.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/store.py src/webapp/main.py src/tests/test_store.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): GET /api/plans/{id}/trajectory serves nominal+worst series"
```

---

## Task 5: `realized_energy_kwh` in the store index (spec §4.1 A3, N5)

**Files:**
- Modify: `webapp/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_save_realized_records_energy_in_index(tmp_path):
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2013-11-11", {})
    store.save_realized("p1", {"total_hvac_energy_kwh": 31000.0, "inlet_violation_steps": 0})
    row = store.get_plan_row("p1")
    assert row["realized_energy_kwh"] == 31000.0
    assert any(p["plan_id"] == "p1" and p["realized_energy_kwh"] == 31000.0
               for p in store.list_plans())
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_store.py -k realized_energy -v`
Expected: FAIL — `KeyError: 'realized_energy_kwh'` (column absent).

- [ ] **Step 3: Add the column + populate it**

In `webapp/store.py::_init_db`, after the `CREATE TABLE` statement, add an idempotent column add:

```python
            # additive migration: realized energy for the History trend
            try:
                c.execute("ALTER TABLE plans ADD COLUMN realized_energy_kwh REAL")
            except sqlite3.OperationalError:
                pass  # column already exists
```

Then extend `save_realized` to update the index:

```python
    def save_realized(self, plan_id: str, realized: dict) -> None:
        (self.plan_dir(plan_id) / "realized.json").write_text(json.dumps(realized, indent=2))
        with self._conn() as c:
            c.execute("UPDATE plans SET realized_energy_kwh=? WHERE plan_id=?",
                      (realized.get("total_hvac_energy_kwh"), plan_id))
```

(`list_plans` already does `SELECT *`, and `get_plan_row` does `SELECT *`, so both pick up the new column automatically.)

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/store.py src/tests/test_store.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): record realized_energy_kwh in the plan index for the History trend"
```

---

## Task 6: Frontend — trajectory chart + History trend (spec §4.1 A3 frontend, N6)

**Files:**
- Modify: `src/frontend/src/api.ts`
- Modify: `src/frontend/src/pages/Review.tsx`
- Modify: `src/frontend/src/pages/History.tsx`
- Test: `src/frontend/src/pages/Review.test.tsx`, `src/frontend/src/pages/History.test.tsx`

- [ ] **Step 1: Extend `api.ts`**

In `frontend/src/api.ts`: add to `PlanSummary` the field `realized_energy_kwh: number | null;` (after `reduction_pct`). Add a trajectory type + client after `getCalibration`:

```typescript
export interface TrajRow { step: number; inlet_temp_max_c: number | null; hvac_power_kw: number | null; pue: number | null; }
export interface Trajectory { nominal: TrajRow[]; worst: TrajRow[]; }
export const getTrajectory = (id: string) => req<Trajectory>(`/api/plans/${id}/trajectory`);
```

- [ ] **Step 2: Add the failing Review test by EDITING the existing file**

`Review.test.tsx` already imports `{ describe, it, expect, vi, beforeEach }` + `{ render, screen, fireEvent, waitFor }` + `Review`, already has one `vi.mock('../api', ...)` factory (lines 5-18), and defines `PLAN_SUMMARY` + `PLAN_DETAIL`. Do NOT append a new import block or a second `vi.mock` — that re-declares identifiers (parse error) and the second mock would clobber the existing `vi.fn()` mocks the other 21 tests rely on.

(a) Add one key to the EXISTING `vi.mock('../api', () => ({ ... }))` factory, after the `getCalibration:` entry:

```typescript
  getTrajectory: vi.fn().mockResolvedValue({
    nominal: [{ step: 0, inlet_temp_max_c: 24, hvac_power_kw: 0.2, pue: 1.2 }],
    worst:  [{ step: 0, inlet_temp_max_c: 28, hvac_power_kw: 0.5, pue: 1.3 }],
  }),
```

(b) Add this `it(...)` INSIDE the existing `describe('Review', () => { ... })` block (reuses the already-imported `listPlans`/`getPlan` and the file's `PLAN_SUMMARY`/`PLAN_DETAIL`):

```typescript
  it('renders the inlet trajectory card', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLAN_SUMMARY]);
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(PLAN_DETAIL);
    render(<Review planId={PLAN_SUMMARY.plan_id} />);
    await waitFor(() => expect(screen.getByText(/Inlet Trajectory/i)).toBeInTheDocument());
  });
```

(The component imports `getTrajectory` from `../api`, which the mock now provides — no extra test import needed.)

- [ ] **Step 3: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- Review`
Expected: the new test FAILS — no "Inlet Trajectory" text yet; the existing 21 tests still pass.

- [ ] **Step 4: Add the trajectory card to `Review.tsx`**

Add the `LineChart` imports to the recharts import (line 2-4): add `LineChart, Line, ReferenceLine, Legend`. Add `getTrajectory, type Trajectory` to the api import. Add state + load:

```tsx
  const [traj, setTraj] = useState<Trajectory | null>(null);
```

In the `selectedId` effect (after `getPlan(...)`), also fetch the trajectory:

```tsx
    getTrajectory(selectedId).then(setTraj).catch(() => setTraj(null));
```

Then, inside the `{!loading && detail && (...)}` grid (e.g. just before the closing `</div>` of the grid, after the bar chart card), add:

```tsx
          {traj && (traj.nominal.length > 0 || traj.worst.length > 0) && (
            <div className="card animate-in animate-in-4">
              <div className="card-header">
                <span className="card-title">Inlet Trajectory</span>
                <span className="text-xs text-dim">nominal vs worst-case scenario · 26 °C cap</span>
              </div>
              <div className="card-body">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={(traj.nominal.length ? traj.nominal : traj.worst).map((r, i) => ({
                    step: r.step,
                    nominal: traj.nominal[i]?.inlet_temp_max_c ?? null,
                    worst: traj.worst[i]?.inlet_temp_max_c ?? null,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
                    <XAxis dataKey="step" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
                    <YAxis domain={[20, 32]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={40} />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={26} stroke="var(--red)" strokeDasharray="4 4" label="26°C cap" />
                    <Line type="monotone" dataKey="nominal" name="Nominal" stroke="rgba(0,200,255,0.9)" dot={false} />
                    <Line type="monotone" dataKey="worst" name="Worst scenario" stroke="rgba(239,68,68,0.9)" dot={false} />
                    <Legend />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
```

- [ ] **Step 5: Run the Review test, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- Review`
Expected: PASS.

- [ ] **Step 6: Add the History trend test + chart (EDIT existing files)**

(a) `History.test.tsx` already imports the vitest/testing-library identifiers + `History` and has `vi.mock('../api', () => ({ listPlans: vi.fn() }))` + a `describe('History', ...)`. Do NOT append a new import block / second `vi.mock` (re-declares identifiers, clobbers `listPlans`). Add ONLY this `it(...)` inside the existing `describe('History', () => { ... })`:

```typescript
  it('renders the predicted-vs-realized trend', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([
      { plan_id: 'p1', week_start: '2026-06-02', status: 'deployed', energy_kwh: 100, reduction_pct: 10, realized_energy_kwh: 120 },
    ]);
    render(<History onReview={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Predicted vs Realized/i)).toBeInTheDocument());
  });
```

(b) In `History.tsx`, add the recharts import: `import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend } from 'recharts';`. The current render returns `{!loading && !error && ( <div className="card bracket-card ..."> …table… </div> )}` — a SINGLE card. Wrap it in a fragment so the trend can be a sibling above: change `{!loading && !error && (` to `{!loading && !error && (<>`, change the matching `)}` (right after that card's closing `</div>`) to `</>)}`, and insert this trend card as the FIRST child after `<>`:

```tsx
          {sorted.some(p => p.realized_energy_kwh != null) && (
            <div className="card animate-in animate-in-1" style={{ marginBottom: 16 }}>
              <div className="card-header">
                <span className="card-title">Predicted vs Realized — HVAC Energy</span>
                <span className="text-xs text-dim">deployed weeks</span>
              </div>
              <div className="card-body">
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={[...sorted].reverse().map(p => ({
                    week: p.week_start, predicted: p.energy_kwh, realized: p.realized_energy_kwh,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
                    <XAxis dataKey="week" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
                    <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={55} />
                    <Tooltip />
                    <Line type="monotone" dataKey="predicted" name="Predicted" stroke="rgba(0,200,255,0.9)" dot={false} />
                    <Line type="monotone" dataKey="realized" name="Realized" stroke="rgba(245,158,11,0.9)" dot={false} />
                    <Legend />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
```

- [ ] **Step 7: Run all frontend tests + build**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass; build clean.

- [ ] **Step 8: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/pages/Review.tsx src/frontend/src/pages/Review.test.tsx src/frontend/src/pages/History.tsx src/frontend/src/pages/History.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): Review inlet trajectory chart + History predicted-vs-realized trend"
```

---

## Task 7: Real-weather pkl + schema 1.3 honest forecast labels (spec §4.3, N7)

**Files:**
- Modify: `planner/recommendation.py`
- Modify: `planner/pipeline.py`
- Test: `tests/test_recommendation.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing recommendation test**

Append to `tests/test_recommendation.py`:

```python
def test_build_recommendation_forecast_meta_schema_1_3():
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from datetime import date
    kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                    inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(
        setpoints=Setpoints(22.0, 7.0, 15.0), kpi=kpi, week_start=date(2013, 11, 11),
        days=7, forecast_method="persistence", search_meta={"evals": 1},
        forecast_meta={"method": "persistence", "weather": "Singapore_Changi_Nov2024-Jan2025.epw",
                       "bands": False})
    assert rec["schema_version"] == "1.3"
    assert rec["forecast"]["weather"] == "Singapore_Changi_Nov2024-Jan2025.epw"
    assert rec["forecast"]["bands"] is False


def test_build_recommendation_defaults_tmy_without_forecast_meta():
    from planner.recommendation import build_recommendation
    from planner.types import Setpoints, WeeklyKPI
    from datetime import date
    kpi = WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
                    inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    rec = build_recommendation(setpoints=Setpoints(22.0, 7.0, 15.0), kpi=kpi,
                               week_start=date(2013, 11, 11), days=7,
                               forecast_method="persistence", search_meta={"evals": 1})
    assert rec["forecast"] == {"method": "persistence", "weather": "TMY-window"}
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py -k forecast_meta -v`
Expected: FAIL — `build_recommendation()` has no `forecast_meta` kwarg.

- [ ] **Step 3: Add `forecast_meta` to `build_recommendation`**

In `planner/recommendation.py`, add the parameter to the signature (after `scenario_diagnostics`):

```python
    scenario_diagnostics: Optional[list] = None,
    forecast_meta: Optional[dict] = None,
) -> dict:
```

Replace the hardcoded forecast line (line 67) with:

```python
        "forecast": forecast_meta if forecast_meta is not None
                    else {"method": forecast_method, "weather": "TMY-window"},
```

And after the `raw_kpi` block (which sets schema 1.2), add:

```python
    if forecast_meta is not None:
        rec["schema_version"] = "1.3"
```

- [ ] **Step 4: Thread `forecast_meta` from the pipeline**

In `planner/pipeline.py::run_weekly_plan`, build `forecast_meta` from the forecast and pass it. After `forecast = forecaster.forecast(...)` (line 44), add:

```python
    import os
    _wf = getattr(forecast, "weather_file", None)
    forecast_meta = {
        "method": getattr(forecast, "method", "persistence"),
        "weather": os.path.basename(_wf) if _wf else "TMY-window",
        "bands": getattr(forecast, "bands", None) is not None,
    }
```

Add `forecast_meta=forecast_meta,` to the `build_recommendation(...)` call.

- [ ] **Step 5: Run tests, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_recommendation.py tests/test_pipeline.py -v`
Expected: PASS. NOTE: existing pipeline tests now produce `schema_version "1.3"` (forecast_meta is always threaded). Update any assertion that pinned `"1.2"` in `tests/test_pipeline.py` to `"1.3"`, and the no-robust test likewise. The `forecast` block in those recs is now `{method, weather: "TMY-window", bands: false}` (the `_FakeForecaster` has no weather_file/bands) — update any assertion that checked the old 2-key forecast dict.

- [ ] **Step 6: Document the pkl regeneration (operational step)**

The production `models/forecaster.pkl` is regenerated to carry the real EPW (data/ is gitignored; this is a runtime step, not a committed artifact). Record the exact command in a comment block — add to the top of `fit_forecaster.py`'s `main` docstring (no behavior change) OR note in the commit body:

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -c "import fit_forecaster; fit_forecaster.main(weather_file='data/weather/Singapore_Changi_Nov2024-Jan2025.epw')"
```

(`fit_forecaster.main` already accepts `weather_file` and records it in the pkl config — verified at `fit_forecaster.py:46,55`. The threading from pkl → forecaster → oracle already exists.)

- [ ] **Step 7: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/recommendation.py src/planner/pipeline.py src/tests/test_recommendation.py src/tests/test_pipeline.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): honest forecast labels + bands in recommendation (schema 1.3); real-weather pkl command"
```

---

## Task 8: Forecast-margin hook in the feasibility gate (spec §4.3, N8)

**Files:**
- Modify: `planner/objective.py`
- Test: `tests/test_objective.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_objective.py`:

```python
def test_inlet_forecast_margin_default_is_noop():
    from planner.objective import ObjectiveWeights, is_feasible
    from planner.types import WeeklyKPI
    k = WeeklyKPI(total_hvac_energy_kwh=10.0, pue_mean=1.2, inlet_temp_max=25.5,
                  inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    assert is_feasible(k, ObjectiveWeights())                      # margin 0 -> feasible


def test_inlet_forecast_margin_tightens_gate():
    from planner.objective import ObjectiveWeights, is_feasible
    from planner.types import WeeklyKPI
    # inlet 25.5 + margin 1.0 = 26.5 > 26 cap -> rejected even with 0 violation steps
    k = WeeklyKPI(total_hvac_energy_kwh=10.0, pue_mean=1.2, inlet_temp_max=25.5,
                  inlet_violation_steps=0, rh_violation_steps=0, feasible=True)
    assert not is_feasible(k, ObjectiveWeights(inlet_forecast_margin=1.0))
    assert is_feasible(k, ObjectiveWeights(inlet_forecast_margin=0.4))   # 25.9 <= 26 -> ok
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_objective.py -k forecast_margin -v`
Expected: FAIL — `ObjectiveWeights` has no `inlet_forecast_margin`.

- [ ] **Step 3: Add the field + gate**

In `planner/objective.py`, add to `ObjectiveWeights` (after `rh_tol_steps`):

```python
    inlet_forecast_margin: float = 0.0   # deg C: pre-tighten the inlet cap (default off)
    inlet_cap: float = 26.0              # hard ITE inlet limit used by the margin gate
```

Extend `is_feasible` (after the `inlet_violation_steps` check, before the rh check):

```python
    if w.inlet_forecast_margin > 0.0 and (kpi.inlet_temp_max + w.inlet_forecast_margin) > w.inlet_cap:
        return False
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_objective.py -v`
Expected: PASS. Run `tests/test_pipeline.py tests/test_robust.py tests/test_beam_search.py` too — they construct `ObjectiveWeights()` (margin default 0.0 → no behavior change), so they stay green.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/objective.py src/tests/test_objective.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): off-by-default inlet_forecast_margin feasibility pre-tighten hook"
```

---

## Task 9: Robust scenario error-handling + ⌈N/2⌉ rule (spec §4.4, N9)

**Files:**
- Modify: `planner/robust.py`
- Test: `tests/test_robust.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_robust.py`:

```python
def test_robust_select_requires_majority_successful_scenarios():
    from planner.robust import robust_select
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    def k(inlet, energy=100.0, feasible=True):
        return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                         inlet_violation_steps=0 if feasible else 5, rh_violation_steps=0, feasible=True)

    finalists = [(Setpoints(22, 7, 15), k(24), 100.0, k(24))]
    # 4 scenarios requested, but only 1 succeeded (3 dropped) -> below ceil(4/2)=2 -> not robust-feasible
    scenario_kpis = [[k(24)]]
    res = robust_select(finalists, scenario_kpis, ObjectiveWeights(), n_requested=4)
    assert res.robust_feasible is False
    assert res.scenarios_ok == 1


def test_robust_select_majority_present_is_feasible():
    from planner.robust import robust_select
    from planner.objective import ObjectiveWeights
    from planner.types import Setpoints, WeeklyKPI

    def k(inlet):
        return WeeklyKPI(total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=inlet,
                         inlet_violation_steps=0, rh_violation_steps=0, feasible=True)

    finalists = [(Setpoints(22, 7, 15), k(24), 100.0, k(24))]
    scenario_kpis = [[k(24), k(25), k(24)]]   # 3 of 4 succeeded, all feasible
    res = robust_select(finalists, scenario_kpis, ObjectiveWeights(), n_requested=4)
    assert res.robust_feasible is True
    assert res.scenarios_ok == 3
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_robust.py -k majority -v`
Expected: FAIL — `robust_select()` has no `n_requested` kwarg / `RobustResult` has no `scenarios_ok`.

- [ ] **Step 3: Add `scenarios_ok` + the ⌈N/2⌉ rule + scenario try/except**

In `planner/robust.py`, add a field to `RobustResult` (after `scenario_diagnostics`):

```python
    scenarios_ok: int = 0                   # scenarios that evaluated successfully
```

Change `robust_select` signature to accept `n_requested` and apply the majority rule. Replace its body's `robust_feasible` computation + the `return`:

```python
def robust_select(finalists: list, scenario_kpis: list,
                  weights: ObjectiveWeights, alpha: float = 0.8,
                  n_requested: Optional[int] = None) -> RobustResult:
    """... A finalist counts as robust-feasible only if it has >= ceil(n_requested/2)
    successful scenarios AND every successful scenario is feasible."""
    import math as _math
    n_scen = len(scenario_kpis[0]) if scenario_kpis else 0
    req = n_requested if n_requested is not None else n_scen
    min_ok = _math.ceil(req / 2) if req else 0
    robust_feasible = [
        bool(ks) and len(ks) >= min_ok and all(is_feasible(k, weights) for k in ks)
        for ks in scenario_kpis
    ]
    pool = [i for i, ok in enumerate(robust_feasible) if ok] or list(range(len(finalists)))

    def cvar_e(i):
        return _cvar([k.total_hvac_energy_kwh for k in scenario_kpis[i]], alpha)

    win = min(pool, key=cvar_e)
    bands = {}
    for key in ROBUST_KEYS:
        vals = [getattr(k, _RKEY_FIELD[key]) for k in scenario_kpis[win]]
        bands[key] = {"p50": _quantile(vals, 0.5), "p90": _quantile(vals, 0.9), "max": max(vals)} if vals else {}
    raw = finalists[win][3] if len(finalists[win]) > 3 else finalists[win][1]
    diagnostics = [
        {"scenario": j, "inlet_temp_max_c": scenario_kpis[win][j].inlet_temp_max,
         "feasible": is_feasible(scenario_kpis[win][j], weights)}
        for j in range(len(scenario_kpis[win]))
    ]
    return RobustResult(
        winner=finalists[win][0], winner_kpi=finalists[win][1],
        robust_feasible=robust_feasible[win], cvar_energy_kwh=cvar_e(win),
        confidence_bands=bands, n_scenarios=req, winner_kpi_raw=raw,
        robust_substituted=(win != 0), scenario_diagnostics=diagnostics,
        scenarios_ok=len(scenario_kpis[win]))
```

In `make_oracle_robust_rerank.rerank`, wrap the per-scenario evaluation in try/except and pass `n_requested`:

```python
    def rerank(finalists, forecast):
        setpoints = [f[0] for f in finalists]
        per_finalist = [[] for _ in finalists]
        for j, sc in enumerate(scenarios):
            sdir = str(Path(log_root) / f"scenario-{j:02d}")
            try:
                sproto = build_plant_prototxt(base_prototxt, sc, sdir)
                oracle = oracle_cls(
                    base_prototxt=sproto, project_root=".",
                    config=replace(oracle_config, log_root=str(Path(sdir) / "oracle")))
                for i, k in enumerate(oracle.evaluate(setpoints, forecast=forecast)):
                    per_finalist[i].append(k)
            except Exception:  # noqa: BLE001 - a failed scenario is dropped, never fatal
                import logging
                logging.getLogger(__name__).warning("robust scenario %d failed; dropping", j)
        return robust_select(finalists, per_finalist, weights, n_requested=len(scenarios))
```

- [ ] **Step 4: Thread `scenarios_ok` into the recommendation**

In `planner/recommendation.py::build_recommendation`, add `scenarios_ok: Optional[int] = None` to the signature and `"scenarios_ok": scenarios_ok,` into the `robust` block dict. In `planner/pipeline.py`, add `scenarios_ok=(robust.scenarios_ok if robust else None),` to the `build_recommendation(...)` call.

- [ ] **Step 5: Run tests, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_robust.py tests/test_recommendation.py tests/test_pipeline.py -v`
Expected: PASS. The existing `test_robust.py` cases call `robust_select(..., n_requested=None)` implicitly (default), so `min_ok` falls back to `n_scen` — for a full-length scenario list that's all-present, behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/robust.py src/planner/recommendation.py src/planner/pipeline.py src/tests/test_robust.py src/tests/test_recommendation.py src/tests/test_pipeline.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): robust scenario error-handling + majority rule + scenarios_ok"
```

---

## Task 10: Best-effort EnergyPlus container teardown (spec §4.4, N10)

**Files:**
- Modify: `planner/oracle_worker.py`
- Test: `tests/test_oracle_worker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle_worker.py`:

```python
def test_teardown_container_is_best_effort():
    from planner.oracle_worker import _teardown_container
    calls = {"stopped": False}

    class _Container:
        def stop(self, timeout=5):
            calls["stopped"] = True
        def remove(self, force=True):
            raise RuntimeError("already gone")   # must be swallowed

    class _Backend:
        container = _Container()

    class _Env:
        class unwrapped:
            eplus_backend = _Backend()

    _teardown_container(_Env())          # must not raise
    assert calls["stopped"] is True
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle_worker.py -k teardown -v`
Expected: FAIL — `ImportError: cannot import name '_teardown_container'`.

- [ ] **Step 3: Add `_teardown_container` and call it in both workers' `finally`**

In `planner/oracle_worker.py`, add:

```python
def _teardown_container(env) -> None:
    """Best-effort stop+remove of the EnergyPlus Docker container so a hung/timed-out
    run doesn't leak the container + BCVTB socket. Fully exception-guarded."""
    backend = getattr(getattr(env, "unwrapped", env), "eplus_backend", None)
    container = getattr(backend, "container", None)
    if container is None:
        return
    try:
        container.stop(timeout=5)
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass
```

Both `evaluate_one` and `evaluate_one_with_samples` (created in Task 2) end with a **textually identical** `finally` block. Add the teardown call to BOTH — the cleanest way is an Edit with `replace_all: true` on the exact current finally text so both functions get it in one go:

Match (current, appears twice):
```python
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
```
Replace-all with:
```python
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
            _teardown_container(env)
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_oracle_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/oracle_worker.py src/tests/test_oracle_worker.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): best-effort EnergyPlus container teardown (no leak on hung run)"
```

---

## Task 11: Docker acceptance — both trajectories emitted + served (spec §7, N11)

**Files:**
- Create: `tests/integration/test_trajectory_emit.py`

- [ ] **Step 1: Write the Docker-gated test**

Create `tests/integration/test_trajectory_emit.py`:

```python
"""Docker-gated: a real plan emits both trajectory CSVs and GET /trajectory serves them.
Run: env -C src sg docker -c "PYTHONPATH=$PWD ../.venv-dtwin/bin/python -m pytest \
  tests/integration/test_trajectory_emit.py -m integration -v"
"""
import pytest

pytestmark = pytest.mark.integration


def test_prevalidation_emits_both_trajectories(tmp_path):
    from webapp.store import PlanStore
    from webapp.jobs import run_plan_job

    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    plan_id = "gds-traj-1day"
    params = {"week_start": "2013-11-11", "days": 1, "grid": 3, "beam_width": 2,
              "levels": 1, "n_workers": 2, "n_scenarios": 2}
    store.create_plan(plan_id, params["week_start"], params)
    run_plan_job(plan_id, params, store, lambda p: None)
    # NOTE: week_start "2013-11-11" assumes models/forecaster.pkl has weather_file=None
    # (TMY) — the state until the Final-Verification real-EPW regen. If the pkl carries the
    # real Nov2024-Jan2025 EPW, use a within-coverage week (e.g. "2024-11-11") instead.

    traj = store.get_trajectory(plan_id)
    assert len(traj["nominal"]) > 0, "nominal trajectory CSV not emitted"
    assert len(traj["worst"]) > 0, "worst-case trajectory CSV not emitted"
    # the worst-case scenario should run at least as hot as nominal
    nmax = max(r["inlet_temp_max_c"] for r in traj["nominal"] if r["inlet_temp_max_c"] is not None)
    wmax = max(r["inlet_temp_max_c"] for r in traj["worst"] if r["inlet_temp_max_c"] is not None)
    assert wmax >= nmax - 0.5
```

- [ ] **Step 2: Verify deselected without Docker**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/integration/test_trajectory_emit.py -v`
Expected: `1 deselected` (no errors on collection).

- [ ] **Step 3: Run under Docker**

Run:
```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src sg docker -c "PYTHONPATH=/mnt/lv/home/hoanghuy/newcode/dctwin/src /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_trajectory_emit.py -m integration -v"
```
Expected: PASS (several minutes — real EnergyPlus). If `worst` is empty, the pre-validation worst-oracle wiring (Task 3) is broken — debug before proceeding.

- [ ] **Step 4: Full unit suite (no regressions)**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`
Expected: all unit pass; the integration tests (NOW tier's + this new one) deselected.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/tests/integration/test_trajectory_emit.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "test(dtwin): Docker acceptance — plan emits + serves nominal & worst trajectories"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test && npm run build`.
- [ ] Docker acceptance (Task 11 Step 3) green.
- [ ] Regenerate `models/forecaster.pkl` with the real EPW (Task 7 Step 6 command) so production runs on real weather.
- [ ] Update memory (`dtwin-dual-loop-framework.md`) with the NEXT-tier completion (schema 1.3, trajectory endpoint, new ObjectiveWeights/RobustResult fields).
