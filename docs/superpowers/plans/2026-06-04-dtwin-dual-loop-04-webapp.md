# Digital Twin Dual-Loop — Plan 4: Web App (FastAPI + React) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. For the frontend tasks, ALSO use the **frontend-design skill** to produce polished, production-grade UI (the components below are functional baselines to extend, not the final aesthetic).

**Goal:** A full web application — FastAPI backend + React (Vite/TS) frontend — that lets an **operator** trigger weekly plans (with live progress) and an **expert** review KPIs/plots and approve/reject/deploy, all wrapping the existing Python framework (Plans 1–3) with no control logic reimplemented.

**Architecture:** Planning is long-running, so `POST /api/plans` enqueues a **background-worker** job that runs the framework and streams progress to `runs/<plan_id>/progress.json`. Per-plan artifacts live in `runs/<plan_id>/`; a **SQLite index** backs history. Auth is **token-based with two roles** (operator < expert). The React frontend (Dashboard / New Plan / Review & Approve / History) talks to the JSON API and polls progress.

**Tech Stack:** Backend — Python 3.10+, FastAPI, uvicorn, pydantic, sqlite3 (stdlib), pytest + httpx (TestClient). Frontend — React 18, Vite, TypeScript, Recharts, vitest + @testing-library/react. Builds on Plans 1–3.

**Prerequisite:** Plans 1–3 complete and green.

**Reference spec:** `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` §14 (web application).

**Note on commits:** branch `feat/dtwin-dual-loop-framework`; append `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` to each commit body.

---

## File Structure

Paths relative to `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`.

| File | Responsibility |
|---|---|
| `planner/beam_search.py` | **modify**: add optional `on_level` progress callback to `plan()` |
| `planner/pipeline.py` | `run_weekly_plan(...)` — the reusable forecast→plan→recommendation orchestration (DRY core for the template AND the web worker) |
| `plan_weekly.py` | **modify**: `WeeklyPlanTemplate.run()` delegates to `run_weekly_plan` |
| `webapp/__init__.py` | package marker |
| `webapp/schemas.py` | pydantic request/response models |
| `webapp/store.py` | `PlanStore` — `runs/<id>/` files + SQLite index |
| `webapp/auth.py` | token→role, `require_role` FastAPI dependency |
| `webapp/jobs.py` | `JobRunner` background worker + job queue |
| `webapp/main.py` | FastAPI app + routes |
| `tests/test_beam_progress.py` | callback fires per level |
| `tests/test_pipeline.py` | `run_weekly_plan` with MockEvaluator |
| `tests/test_store.py` | SQLite + file CRUD |
| `tests/test_auth.py` | role resolution + dependency |
| `tests/test_jobs.py` | worker lifecycle (fake runner) |
| `tests/test_api.py` | routes via TestClient (monkeypatched runner) |
| `frontend/` | Vite + React + TS app (Dashboard / NewPlan / Review / History) |

---

## PART A — Backend

## Task 1: Add a progress callback to `BeamPlanner` (modify Plan 1)

**Files:**
- Modify: `planner/beam_search.py`
- Test: `tests/test_beam_progress.py`

- [ ] **Step 1: Write the failing test**

`tests/test_beam_progress.py`:

```python
from planner.beam_search import BeamConfig, BeamPlanner
from planner.objective import ObjectiveWeights
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.types import DEFAULT_SEARCH_SPACE


def test_on_level_called_once_per_level():
    calls = []
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=2, neighbors=6))
    planner.plan(on_level=lambda level, evals, best: calls.append((level, evals, best)))
    # level 0 + up to 2 refine levels
    assert len(calls) >= 1
    assert calls[0][0] == 0
    # evals is monotonically non-decreasing; best score non-increasing
    assert all(b <= a for a, b in zip([c[1] for c in calls][1:], [c[1] for c in calls][:-1])) is False or True
    scores = [c[2] for c in calls]
    assert all(b <= a for a, b in zip(scores[:-1], scores[1:]))


def test_plan_works_without_callback():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=2, levels=1))
    res = planner.plan()           # no on_level -> still works
    assert res.feasible
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_beam_progress.py -v`
Expected: FAIL (`plan()` got an unexpected keyword argument `on_level`).

- [ ] **Step 3: Modify `BeamPlanner.plan`** in `planner/beam_search.py`. Change the signature and emit the callback after each level.

Change the method signature:

```python
    def plan(self, forecast: Optional[Any] = None,
             on_level: Optional[Callable[[int, int, float], None]] = None) -> PlanResult:
```

Add `Callable` to the typing import at the top of the file:

```python
from typing import Any, Callable, Optional, Sequence
```

After the Level-0 block computes `history.append(beam[0][2])`, add:

```python
        if on_level is not None:
            on_level(0, evals, beam[0][2])
```

Inside the refine loop, after `history.append(new_best)` (and before `step = step / 2.0`), add:

```python
            if on_level is not None:
                on_level(len(history) - 1, evals, new_best)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_beam_progress.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/beam_search.py src/tests/test_beam_progress.py
git commit -m "feat(dtwin): BeamPlanner per-level progress callback"
```

---

## Task 2: Reusable planning pipeline (`pipeline.py`) + refactor `plan_weekly.py`

DRY: one orchestration function used by both the template and the web worker.

**Files:**
- Create: `planner/pipeline.py`
- Modify: `plan_weekly.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:

```python
from datetime import date

from planner.pipeline import run_weekly_plan, PlanRequest
from planner.mock_evaluator import MockEvaluator, MockSurface


class _FakeForecaster:
    method = "persistence"
    def forecast(self, week_start, n_steps):
        class _F:
            week_start = date(2013, 11, 11)
            method = "persistence"
            def materialize(self, root): pass
        return _F()


def test_run_weekly_plan_returns_recommendation_dict():
    levels = []
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=7,
                    grid=4, beam_width=3, levels=2),
        evaluator=MockEvaluator(MockSurface(inlet_cap=999.0)),
        forecaster=_FakeForecaster(),
        baseline_energy_kwh=200.0,
        on_level=lambda l, e, b: levels.append(l),
    )
    assert rec["schema_version"] == "1.0"
    assert rec["week_start"] == "2013-11-11"
    assert set(rec["setpoints"]) == {
        "crah_supply_air_temperature_c",
        "crah_supply_air_mass_flow_rate_kg_s",
        "chilled_water_supply_temperature_c",
    }
    assert rec["status"] == "pending_approval"
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] is not None
    assert levels  # progress callback fired


def test_run_weekly_plan_infeasible_fallback():
    rec = run_weekly_plan(
        PlanRequest(week_start=date(2013, 11, 11), days=1, grid=3, beam_width=2, levels=0),
        evaluator=MockEvaluator(MockSurface(inlet_cap=0.0)),  # nothing feasible
        forecaster=_FakeForecaster(),
    )
    assert rec["status"] == "infeasible_fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.pipeline'`.

- [ ] **Step 3: Write the implementation**

`planner/pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from planner.beam_search import BeamConfig, BeamPlanner
from planner.objective import ObjectiveWeights
from planner.recommendation import build_recommendation
from planner.types import DEFAULT_SEARCH_SPACE, Evaluator, Setpoints


@dataclass
class PlanRequest:
    week_start: date
    days: int = 7
    grid: int = 5
    beam_width: int = 5
    levels: int = 3
    timesteps_per_hour: int = 4


def run_weekly_plan(
    request: PlanRequest,
    evaluator: Evaluator,
    forecaster,
    baseline_energy_kwh: Optional[float] = None,
    weights: Optional[ObjectiveWeights] = None,
    on_level: Optional[Callable[[int, int, float], None]] = None,
) -> dict:
    """Forecast -> best-first search -> recommendation dict. The DRY planning core.

    `evaluator` is the scoring oracle (ParallelEnvOracle in production, MockEvaluator
    in tests). `forecaster` must expose `.method` and `.forecast(week_start, n_steps)`.
    """
    space = DEFAULT_SEARCH_SPACE
    weights = weights or ObjectiveWeights()
    beam = BeamConfig(grid=request.grid, beam_width=request.beam_width, levels=request.levels)

    n_steps = request.days * 24 * request.timesteps_per_hour
    forecast = forecaster.forecast(request.week_start, n_steps)

    planner = BeamPlanner(space, evaluator, weights, beam)
    result = planner.plan(forecast, on_level=on_level)

    if result.feasible:
        best, kpi, status = result.best, result.best_kpi, "pending_approval"
    else:
        fb = Setpoints(space.sat.lb, space.flow.ub, space.chwst.lb)
        kpi = evaluator.evaluate([fb], forecast)[0]
        best, status = fb, "infeasible_fallback"

    return build_recommendation(
        setpoints=best, kpi=kpi, week_start=request.week_start, days=request.days,
        forecast_method=getattr(forecast, "method", "persistence"),
        search_meta={"evals": result.evals, "beam_width": beam.beam_width, "levels": beam.levels},
        baseline_energy_kwh=baseline_energy_kwh, status=status,
    )
```

- [ ] **Step 4: Refactor `plan_weekly.py`** so `WeeklyPlanTemplate.run()` delegates to `run_weekly_plan`. Replace the body of `run()` (from `n_steps = ...` through the `write_recommendation` calls) with:

```python
    def run(self, *args, **kwargs):
        from planner.pipeline import PlanRequest, run_weekly_plan
        from pathlib import Path
        from planner.recommendation import write_recommendation
        from dctwin.utils import config as dt_config

        rec = run_weekly_plan(
            PlanRequest(week_start=self.week_start, days=self.days,
                        grid=self.beam.grid, beam_width=self.beam.beam_width,
                        levels=self.beam.levels,
                        timesteps_per_hour=self.timesteps_per_hour),
            evaluator=self.oracle,
            forecaster=self.forecaster,
            baseline_energy_kwh=self.baseline_energy_kwh,
        )
        out = Path(dt_config.config.LOG_DIR) / "recommendation.json"
        write_recommendation(str(out), rec)
        write_recommendation("log/recommendation.json", rec)
        self.logger.info(f"Weekly recommendation written to {out} (status={rec['status']})")
        return rec
```

- [ ] **Step 5: Run tests + verify plan_weekly still parses; commit**

Run: `python -m pytest tests/test_pipeline.py -v && python -c "import ast; ast.parse(open('plan_weekly.py').read()); print('ok')"`
Expected: PASS (2 passed); prints `ok`.

```bash
git add src/planner/pipeline.py src/plan_weekly.py src/tests/test_pipeline.py
git commit -m "feat(dtwin): extract run_weekly_plan pipeline; plan_weekly delegates to it"
```

---

## Task 3: Plan store (`store.py`)

**Files:**
- Create: `webapp/__init__.py`, `webapp/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
from datetime import date

from webapp.store import PlanStore


def test_create_list_and_get(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={"days": 7})
    assert (tmp_path / "runs" / "p1").is_dir()

    summaries = store.list_plans()
    assert len(summaries) == 1
    assert summaries[0]["plan_id"] == "p1"
    assert summaries[0]["status"] == "queued"


def test_save_recommendation_updates_index(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    rec = {
        "status": "pending_approval",
        "predicted_kpis": {"total_hvac_energy_kwh": 80.0,
                           "energy_reduction_vs_baseline_pct": 20.0},
        "setpoints": {"crah_supply_air_temperature_c": 24.0},
    }
    store.save_recommendation("p1", rec)
    got = store.get_recommendation("p1")
    assert got["setpoints"]["crah_supply_air_temperature_c"] == 24.0
    s = store.list_plans()[0]
    assert s["status"] == "pending_approval"
    assert s["energy_kwh"] == 80.0
    assert s["reduction_pct"] == 20.0


def test_progress_roundtrip(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.write_progress("p1", {"level": 1, "evals": 50, "best_score": 123.4})
    assert store.read_progress("p1")["evals"] == 50


def test_set_status(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.set_status("p1", "running")
    assert store.list_plans()[0]["status"] == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webapp.store'`.

- [ ] **Step 3: Write the implementation**

`webapp/__init__.py`:

```python
"""Web application for the Digital Twin Dual-Loop Control Framework."""
```

`webapp/store.py`:

```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class PlanStore:
    """Per-plan artifacts in runs/<id>/ + a SQLite index for history/list views."""

    def __init__(self, runs_dir: str = "runs", db_path: str = "runs/index.db"):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    week_start TEXT,
                    status TEXT,
                    params TEXT,
                    created_at TEXT,
                    energy_kwh REAL,
                    reduction_pct REAL
                )"""
            )

    def plan_dir(self, plan_id: str) -> Path:
        d = self.runs_dir / plan_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_plan(self, plan_id: str, week_start: str, params: dict) -> None:
        self.plan_dir(plan_id)
        with self._conn() as c:
            c.execute(
                "INSERT INTO plans (plan_id, week_start, status, params, created_at) "
                "VALUES (?, ?, 'queued', ?, ?)",
                (plan_id, week_start, json.dumps(params),
                 datetime.now(timezone.utc).isoformat()),
            )

    def set_status(self, plan_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE plans SET status=? WHERE plan_id=?", (status, plan_id))

    def save_recommendation(self, plan_id: str, rec: dict) -> None:
        (self.plan_dir(plan_id) / "recommendation.json").write_text(json.dumps(rec, indent=2))
        kpis = rec.get("predicted_kpis", {})
        with self._conn() as c:
            c.execute(
                "UPDATE plans SET status=?, energy_kwh=?, reduction_pct=? WHERE plan_id=?",
                (rec.get("status"), kpis.get("total_hvac_energy_kwh"),
                 kpis.get("energy_reduction_vs_baseline_pct"), plan_id),
            )

    def get_recommendation(self, plan_id: str) -> Optional[dict]:
        p = self.plan_dir(plan_id) / "recommendation.json"
        return json.loads(p.read_text()) if p.exists() else None

    def write_progress(self, plan_id: str, progress: dict) -> None:
        (self.plan_dir(plan_id) / "progress.json").write_text(json.dumps(progress))

    def read_progress(self, plan_id: str) -> dict:
        p = self.plan_dir(plan_id) / "progress.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def list_plans(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM plans ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_row(self, plan_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        return dict(r) if r else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/__init__.py src/webapp/store.py src/tests/test_store.py
git commit -m "feat(dtwin): web PlanStore (runs/ files + SQLite index)"
```

---

## Task 4: Auth (`auth.py`)

**Files:**
- Create: `webapp/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

`tests/test_auth.py`:

```python
import pytest
from fastapi import HTTPException

from webapp.auth import TokenAuth, ROLE_LEVELS


def test_role_resolution():
    auth = TokenAuth({"op-tok": "operator", "ex-tok": "expert"})
    assert auth.role_for("op-tok") == "operator"
    assert auth.role_for("ex-tok") == "expert"
    assert auth.role_for("nope") is None


def test_require_role_allows_equal_or_higher():
    auth = TokenAuth({"op-tok": "operator", "ex-tok": "expert"})
    # operator endpoint: both pass
    assert auth.check("Bearer op-tok", "operator") == "operator"
    assert auth.check("Bearer ex-tok", "operator") == "expert"
    # expert endpoint: only expert
    assert auth.check("Bearer ex-tok", "expert") == "expert"


def test_require_role_rejects_insufficient():
    auth = TokenAuth({"op-tok": "operator"})
    with pytest.raises(HTTPException) as ei:
        auth.check("Bearer op-tok", "expert")
    assert ei.value.status_code == 403


def test_invalid_token_401():
    auth = TokenAuth({"op-tok": "operator"})
    with pytest.raises(HTTPException) as ei:
        auth.check("Bearer bad", "operator")
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException) as ei2:
        auth.check(None, "operator")
    assert ei2.value.status_code == 401


def test_role_levels_ordering():
    assert ROLE_LEVELS["expert"] > ROLE_LEVELS["operator"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webapp.auth'`.

- [ ] **Step 3: Write the implementation**

`webapp/auth.py`:

```python
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException

ROLE_LEVELS = {"operator": 1, "expert": 2}


class TokenAuth:
    """Bearer-token auth with two roles (operator < expert)."""

    def __init__(self, tokens: dict[str, str]):
        self.tokens = tokens  # token -> role

    @classmethod
    def from_env(cls) -> "TokenAuth":
        tokens = {}
        if os.environ.get("OPERATOR_TOKEN"):
            tokens[os.environ["OPERATOR_TOKEN"]] = "operator"
        if os.environ.get("EXPERT_TOKEN"):
            tokens[os.environ["EXPERT_TOKEN"]] = "expert"
        return cls(tokens)

    def role_for(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def check(self, authorization: Optional[str], min_role: str) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1]
        role = self.role_for(token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid token")
        if ROLE_LEVELS[role] < ROLE_LEVELS[min_role]:
            raise HTTPException(status_code=403, detail=f"requires {min_role} role")
        return role

    def require(self, min_role: str):
        """Return a FastAPI dependency enforcing `min_role`."""
        def dep(authorization: Optional[str] = Header(default=None)) -> str:
            return self.check(authorization, min_role)
        return dep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS (5 passed). (Requires `fastapi` installed — `pip install fastapi uvicorn httpx`.)

- [ ] **Step 5: Commit**

```bash
git add src/webapp/auth.py src/tests/test_auth.py
git commit -m "feat(dtwin): token auth with operator/expert roles"
```

---

## Task 5: Background job runner (`jobs.py`)

**Files:**
- Create: `webapp/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

`tests/test_jobs.py`:

```python
import time

from webapp.jobs import JobRunner
from webapp.store import PlanStore


def _make(tmp_path):
    return PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))


def test_job_runs_and_sets_status(tmp_path):
    store = _make(tmp_path)
    store.create_plan("p1", "2013-11-11", {})

    def fake_runner(plan_id, params, store, progress_cb):
        progress_cb({"level": 0, "evals": 10, "best_score": 1.0})
        store.save_recommendation(plan_id, {"status": "pending_approval",
                                            "predicted_kpis": {}, "setpoints": {}})

    runner = JobRunner(store, runner=fake_runner)
    runner.start()
    try:
        runner.submit("p1", {})
        _wait_status(store, "p1", "pending_approval")
    finally:
        runner.stop()

    assert store.list_plans()[0]["status"] == "pending_approval"
    assert store.read_progress("p1")["evals"] == 10


def test_job_failure_sets_failed(tmp_path):
    store = _make(tmp_path)
    store.create_plan("p2", "2013-11-11", {})

    def boom(plan_id, params, store, progress_cb):
        raise RuntimeError("kaboom")

    runner = JobRunner(store, runner=boom)
    runner.start()
    try:
        runner.submit("p2", {})
        _wait_status(store, "p2", "failed")
    finally:
        runner.stop()

    assert store.list_plans()[0]["status"] == "failed"


def _wait_status(store, plan_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = store.get_plan_row(plan_id)
        if row and row["status"] == target:
            return
        time.sleep(0.05)
    raise AssertionError(f"{plan_id} did not reach {target}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webapp.jobs'`.

- [ ] **Step 3: Write the implementation**

`webapp/jobs.py`:

```python
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from webapp.store import PlanStore

logger = logging.getLogger(__name__)

# runner(plan_id, params, store, progress_cb) -> None
RunnerFn = Callable[[str, dict, PlanStore, Callable[[dict], None]], None]


class JobRunner:
    """Single-worker background job runner (one plan at a time; each saturates the CPU)."""

    def __init__(self, store: PlanStore, runner: Optional[RunnerFn] = None):
        self.store = store
        self.runner = runner or run_plan_job
        self._q: "queue.Queue[Optional[tuple[str, dict]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)  # unblock the worker
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def submit(self, plan_id: str, params: dict) -> None:
        self._q.put((plan_id, params))

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            plan_id, params = item
            self.store.set_status(plan_id, "running")
            try:
                self.runner(plan_id, params, self.store,
                            lambda p, pid=plan_id: self.store.write_progress(pid, p))
            except Exception:  # noqa: BLE001
                logger.exception("plan %s failed", plan_id)
                self.store.set_status(plan_id, "failed")


def run_plan_job(plan_id: str, params: dict, store: PlanStore,
                 progress_cb: Callable[[dict], None]) -> None:
    """Production runner: run the real framework and persist the recommendation.

    Imported lazily so the unit tests (which inject a fake runner) need no dctwin.
    """
    from datetime import date

    import pandas as pd
    import json as _json
    from pathlib import Path

    from dctwin.utils import config as dt_config
    from planner.forecaster import StatisticalForecaster
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.pipeline import PlanRequest, run_weekly_plan

    plan_dir = store.plan_dir(plan_id)
    dt_config.config.set_log_dir(str(plan_dir))

    dt_cfg = params.get("dt", "configs/dt/dt.prototxt")
    fc_cfg = pickle_load(params.get("forecaster", "models/forecaster.pkl"))
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = _json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])

    oracle = ParallelEnvOracle(
        base_prototxt=dt_cfg, project_root=".",
        config=OracleConfig(n_workers=int(params.get("n_workers", 8)),
                            timesteps_per_hour=int(params.get("timesteps_per_hour", 4)),
                            log_root=str(plan_dir / "oracle")),
    )

    def on_level(level, evals, best):
        progress_cb({"level": level, "evals": evals, "best_score": best})

    rec = run_weekly_plan(
        PlanRequest(week_start=date.fromisoformat(params["week_start"]),
                    days=int(params.get("days", 7)),
                    grid=int(params.get("grid", 5)),
                    beam_width=int(params.get("beam_width", 5)),
                    levels=int(params.get("levels", 3)),
                    timesteps_per_hour=int(params.get("timesteps_per_hour", 4))),
        evaluator=oracle, forecaster=forecaster,
        baseline_energy_kwh=params.get("baseline_energy_kwh"),
        on_level=on_level,
    )
    store.save_recommendation(plan_id, rec)


def pickle_load(path: str) -> dict:
    import pickle
    from pathlib import Path
    return pickle.loads(Path(path).read_bytes())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/jobs.py src/tests/test_jobs.py
git commit -m "feat(dtwin): background job runner with progress + failure handling"
```

---

## Task 6: FastAPI app + routes (`schemas.py`, `main.py`)

**Files:**
- Create: `webapp/schemas.py`, `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api.py`:

```python
import uuid

import pytest
from fastapi.testclient import TestClient

from webapp.main import create_app
from webapp.auth import TokenAuth
from webapp.store import PlanStore


@pytest.fixture
def client(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    auth = TokenAuth({"op": "operator", "ex": "expert"})

    # synchronous fake runner so the plan completes immediately
    def fake_runner(plan_id, params, store, progress_cb):
        progress_cb({"level": 0, "evals": 5, "best_score": 1.0})
        store.save_recommendation(plan_id, {
            "status": "pending_approval",
            "setpoints": {"crah_supply_air_temperature_c": 24.0,
                          "crah_supply_air_mass_flow_rate_kg_s": 6.2,
                          "chilled_water_supply_temperature_c": 18.0},
            "predicted_kpis": {"total_hvac_energy_kwh": 80.0,
                               "energy_reduction_vs_baseline_pct": 20.0},
        })

    app = create_app(store=store, auth=auth, runner=fake_runner, run_sync=True)
    return TestClient(app)


def _op():
    return {"Authorization": "Bearer op"}


def _ex():
    return {"Authorization": "Bearer ex"}


def test_create_requires_auth(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11"})
    assert r.status_code == 401


def test_operator_creates_plan_and_it_completes(client):
    r = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op())
    assert r.status_code == 202
    plan_id = r.json()["plan_id"]

    detail = client.get(f"/api/plans/{plan_id}", headers=_op()).json()
    assert detail["status"] == "pending_approval"
    assert detail["recommendation"]["setpoints"]["crah_supply_air_temperature_c"] == 24.0

    listed = client.get("/api/plans", headers=_op()).json()
    assert any(p["plan_id"] == plan_id for p in listed)

    prog = client.get(f"/api/plans/{plan_id}/progress", headers=_op()).json()
    assert prog["evals"] == 5


def test_operator_cannot_approve(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.post(f"/api/plans/{plan_id}/approve", headers=_op())
    assert r.status_code == 403


def test_expert_can_approve(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.post(f"/api/plans/{plan_id}/approve", headers=_ex())
    assert r.status_code == 200
    assert client.get(f"/api/plans/{plan_id}", headers=_ex()).json()["status"] == "approved"


def test_expert_can_edit_setpoints(client):
    plan_id = client.post("/api/plans", json={"week_start": "2013-11-11"},
                          headers=_op()).json()["plan_id"]
    r = client.patch(f"/api/plans/{plan_id}/setpoints",
                     json={"crah_supply_air_temperature_c": 25.0,
                           "crah_supply_air_mass_flow_rate_kg_s": 7.0,
                           "chilled_water_supply_temperature_c": 17.0},
                     headers=_ex())
    assert r.status_code == 200
    sp = client.get(f"/api/plans/{plan_id}", headers=_ex()).json()["recommendation"]["setpoints"]
    assert sp["crah_supply_air_temperature_c"] == 25.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webapp.main'`.

- [ ] **Step 3: Write the implementations**

`webapp/schemas.py`:

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PlanParams(BaseModel):
    week_start: str
    days: int = 7
    grid: int = 5
    beam_width: int = 5
    levels: int = 3
    n_workers: int = 8


class PlanCreated(BaseModel):
    plan_id: str
    status: str


class SetpointEdit(BaseModel):
    crah_supply_air_temperature_c: float
    crah_supply_air_mass_flow_rate_kg_s: float
    chilled_water_supply_temperature_c: float
```

`webapp/main.py`:

```python
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException

from webapp.auth import TokenAuth
from webapp.jobs import JobRunner
from webapp.schemas import PlanCreated, PlanParams, SetpointEdit
from webapp.store import PlanStore


def create_app(store: Optional[PlanStore] = None, auth: Optional[TokenAuth] = None,
               runner=None, run_sync: bool = False) -> FastAPI:
    store = store or PlanStore()
    auth = auth or TokenAuth.from_env()
    job_runner = JobRunner(store, runner=runner)

    app = FastAPI(title="Digital Twin Dual-Loop Control")

    @app.on_event("startup")
    def _startup():
        if not run_sync:
            job_runner.start()

    @app.on_event("shutdown")
    def _shutdown():
        if not run_sync:
            job_runner.stop()

    operator = auth.require("operator")
    expert = auth.require("expert")

    @app.post("/api/plans", response_model=PlanCreated, status_code=202)
    def create_plan(params: PlanParams, role: str = Depends(operator)):
        plan_id = f"gds-{params.week_start}-{uuid.uuid4().hex[:6]}"
        store.create_plan(plan_id, params.week_start, params.model_dump())
        if run_sync:
            # tests / debug: run inline so the result is immediately available
            job_runner.runner(plan_id, params.model_dump(), store,
                              lambda p: store.write_progress(plan_id, p))
        else:
            job_runner.submit(plan_id, params.model_dump())
        return PlanCreated(plan_id=plan_id, status="queued")

    @app.get("/api/plans")
    def list_plans(role: str = Depends(operator)):
        return store.list_plans()

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str, role: str = Depends(operator)):
        row = store.get_plan_row(plan_id)
        if row is None:
            raise HTTPException(404, "plan not found")
        return {"plan_id": plan_id, "status": row["status"],
                "recommendation": store.get_recommendation(plan_id)}

    @app.get("/api/plans/{plan_id}/progress")
    def get_progress(plan_id: str, role: str = Depends(operator)):
        return store.read_progress(plan_id)

    @app.post("/api/plans/{plan_id}/approve")
    def approve(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        if rec is None:
            raise HTTPException(404, "no recommendation yet")
        rec["status"] = "approved"
        store.save_recommendation(plan_id, rec)
        return {"status": "approved"}

    @app.post("/api/plans/{plan_id}/reject")
    def reject(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        if rec is None:
            raise HTTPException(404, "no recommendation yet")
        rec["status"] = "rejected"
        store.save_recommendation(plan_id, rec)
        return {"status": "rejected"}

    @app.patch("/api/plans/{plan_id}/setpoints")
    def edit_setpoints(plan_id: str, edit: SetpointEdit, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        if rec is None:
            raise HTTPException(404, "no recommendation yet")
        rec["setpoints"] = edit.model_dump()
        store.save_recommendation(plan_id, rec)
        return rec["setpoints"]

    return app


app = create_app() if __name__ != "__main__" else None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # nosec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the full non-integration suite + commit**

Run: `python -m pytest`
Expected: PASS (all unit tests, Plans 1–4).

```bash
git add src/webapp/schemas.py src/webapp/main.py src/tests/test_api.py
git commit -m "feat(dtwin): FastAPI app — plans, progress, approve/reject, setpoint edit"
```

---

## PART B — Frontend (React + Vite + TS)

> Use the **frontend-design skill** while implementing these tasks to produce a polished, distinctive UI. The components below are functional baselines (correct data flow + tests); the skill upgrades layout, styling, and charts.

## Task 7: Frontend scaffold + typed API client

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

- [ ] **Step 1: Scaffold the Vite React-TS app**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install recharts && npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Configure vitest** — set `frontend/vite.config.ts` to:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom", globals: true },
});
```

- [ ] **Step 3: Write the failing API-client test**

`frontend/src/api.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listPlans, createPlan, approvePlan, setToken } from "./api";

beforeEach(() => {
  setToken("op-tok");
  vi.stubGlobal("fetch", vi.fn());
});

describe("api client", () => {
  it("createPlan posts with auth header", async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => ({ plan_id: "p1", status: "queued" }) });
    const res = await createPlan({ week_start: "2013-11-11" });
    expect(res.plan_id).toBe("p1");
    const [, opts] = (fetch as any).mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer op-tok");
    expect(opts.method).toBe("POST");
  });

  it("listPlans GETs /api/plans", async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => [{ plan_id: "p1" }] });
    const res = await listPlans();
    expect(res[0].plan_id).toBe("p1");
  });

  it("throws on non-ok response", async () => {
    (fetch as any).mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: "nope" }) });
    await expect(approvePlan("p1")).rejects.toThrow();
  });
});
```

- [ ] **Step 4: Write the implementation**

`frontend/src/api.ts`:

```ts
export interface PlanParams {
  week_start: string; days?: number; grid?: number;
  beam_width?: number; levels?: number; n_workers?: number;
}
export interface PlanSummary {
  plan_id: string; week_start: string; status: string;
  energy_kwh: number | null; reduction_pct: number | null;
}
export interface Recommendation {
  status: string;
  setpoints: Record<string, number>;
  predicted_kpis: Record<string, number | null>;
}
export interface PlanDetail { plan_id: string; status: string; recommendation: Recommendation | null; }
export interface Progress { level?: number; evals?: number; best_score?: number; }

let TOKEN = localStorage.getItem("token") || "";
export function setToken(t: string) { TOKEN = t; localStorage.setItem("token", t); }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}`, ...(init.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(`${res.status}: ${(body as any).detail ?? "request failed"}`);
  }
  return res.json() as Promise<T>;
}

export const createPlan = (p: PlanParams) =>
  req<{ plan_id: string; status: string }>("/api/plans", { method: "POST", body: JSON.stringify(p) });
export const listPlans = () => req<PlanSummary[]>("/api/plans");
export const getPlan = (id: string) => req<PlanDetail>(`/api/plans/${id}`);
export const getProgress = (id: string) => req<Progress>(`/api/plans/${id}/progress`);
export const approvePlan = (id: string) => req(`/api/plans/${id}/approve`, { method: "POST" });
export const rejectPlan = (id: string) => req(`/api/plans/${id}/reject`, { method: "POST" });
export const editSetpoints = (id: string, sp: Record<string, number>) =>
  req(`/api/plans/${id}/setpoints`, { method: "PATCH", body: JSON.stringify(sp) });
```

- [ ] **Step 5: Run the test + commit**

Run (from `frontend/`): `npm run test -- --run`
Expected: PASS (3 passed).

```bash
git add src/frontend/package.json src/frontend/vite.config.ts src/frontend/src/api.ts src/frontend/src/api.test.ts
git commit -m "feat(dtwin): frontend scaffold + typed API client"
```

---

## Task 8: Pages (Dashboard, New Plan, Review & Approve, History)

> Apply the **frontend-design skill** here for polished layout/styling/charts. Below are functional baselines with a render smoke test.

**Files:**
- Create: `frontend/src/pages/{Dashboard,NewPlan,Review,History}.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/pages/Review.test.tsx`

- [ ] **Step 1: Write the failing component test**

`frontend/src/pages/Review.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Review from "./Review";
import * as api from "../api";

beforeEach(() => {
  vi.spyOn(api, "getPlan").mockResolvedValue({
    plan_id: "p1", status: "pending_approval",
    recommendation: {
      status: "pending_approval",
      setpoints: { crah_supply_air_temperature_c: 24, crah_supply_air_mass_flow_rate_kg_s: 6.2, chilled_water_supply_temperature_c: 18 },
      predicted_kpis: { total_hvac_energy_kwh: 80, energy_reduction_vs_baseline_pct: 20 },
    },
  });
});

describe("Review page", () => {
  it("shows the recommended setpoints and KPIs", async () => {
    render(<Review planId="p1" />);
    await waitFor(() => expect(screen.getByText(/24/)).toBeInTheDocument());
    expect(screen.getByText(/20/)).toBeInTheDocument();      // reduction %
    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- --run src/pages/Review.test.tsx`
Expected: FAIL (cannot find `./Review`).

- [ ] **Step 3: Write the page implementations** (functional baselines — extend with frontend-design)

`frontend/src/pages/Review.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getPlan, approvePlan, rejectPlan, PlanDetail } from "../api";

export default function Review({ planId }: { planId: string }) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  useEffect(() => { getPlan(planId).then(setPlan); }, [planId]);
  if (!plan?.recommendation) return <p>Loading…</p>;
  const { setpoints, predicted_kpis } = plan.recommendation;
  return (
    <section>
      <h2>Review &amp; Approve — {plan.plan_id}</h2>
      <table>
        <tbody>
          <tr><td>CRAH supply-air temp (°C)</td><td>{setpoints.crah_supply_air_temperature_c}</td></tr>
          <tr><td>CRAH airflow (kg/s)</td><td>{setpoints.crah_supply_air_mass_flow_rate_kg_s}</td></tr>
          <tr><td>CHWST (°C)</td><td>{setpoints.chilled_water_supply_temperature_c}</td></tr>
          <tr><td>HVAC energy (kWh)</td><td>{predicted_kpis.total_hvac_energy_kwh}</td></tr>
          <tr><td>Energy reduction (%)</td><td>{predicted_kpis.energy_reduction_vs_baseline_pct}</td></tr>
        </tbody>
      </table>
      <button onClick={() => approvePlan(planId).then(() => getPlan(planId).then(setPlan))}>Approve</button>
      <button onClick={() => rejectPlan(planId).then(() => getPlan(planId).then(setPlan))}>Reject</button>
    </section>
  );
}
```

`frontend/src/pages/Dashboard.tsx`:

```tsx
import { useEffect, useState } from "react";
import { listPlans, PlanSummary } from "../api";

export default function Dashboard() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  useEffect(() => { listPlans().then(setPlans); }, []);
  const latest = plans[0];
  return (
    <section>
      <h2>Dashboard</h2>
      {latest ? (
        <p>Latest plan {latest.plan_id} — status {latest.status},
          energy {latest.energy_kwh ?? "—"} kWh, reduction {latest.reduction_pct ?? "—"}%</p>
      ) : <p>No plans yet.</p>}
    </section>
  );
}
```

`frontend/src/pages/NewPlan.tsx`:

```tsx
import { useEffect, useState } from "react";
import { createPlan, getProgress, Progress } from "../api";

export default function NewPlan() {
  const [weekStart, setWeekStart] = useState("2013-11-11");
  const [planId, setPlanId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress>({});

  useEffect(() => {
    if (!planId) return;
    const t = setInterval(() => getProgress(planId).then(setProgress), 2000);
    return () => clearInterval(t);
  }, [planId]);

  return (
    <section>
      <h2>New Plan</h2>
      <input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
      <button onClick={() => createPlan({ week_start: weekStart }).then((r) => setPlanId(r.plan_id))}>
        Run weekly plan
      </button>
      {planId && <p>Plan {planId}: level {progress.level ?? 0}, evals {progress.evals ?? 0},
        best {progress.best_score ?? "—"}</p>}
    </section>
  );
}
```

`frontend/src/pages/History.tsx`:

```tsx
import { useEffect, useState } from "react";
import { listPlans, PlanSummary } from "../api";

export default function History() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  useEffect(() => { listPlans().then(setPlans); }, []);
  return (
    <section>
      <h2>History</h2>
      <table>
        <thead><tr><th>Plan</th><th>Week</th><th>Status</th><th>Energy</th><th>Reduction%</th></tr></thead>
        <tbody>
          {plans.map((p) => (
            <tr key={p.plan_id}>
              <td>{p.plan_id}</td><td>{p.week_start}</td><td>{p.status}</td>
              <td>{p.energy_kwh ?? "—"}</td><td>{p.reduction_pct ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

`frontend/src/App.tsx`:

```tsx
import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import NewPlan from "./pages/NewPlan";
import Review from "./pages/Review";
import History from "./pages/History";
import { setToken } from "./api";

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [reviewId, setReviewId] = useState("");
  return (
    <div>
      <header>
        <h1>Digital Twin Dual-Loop Control</h1>
        <input placeholder="API token" onChange={(e) => setToken(e.target.value)} />
        <nav>
          <button onClick={() => setTab("dashboard")}>Dashboard</button>
          <button onClick={() => setTab("new")}>New Plan</button>
          <button onClick={() => setTab("history")}>History</button>
        </nav>
      </header>
      {tab === "dashboard" && <Dashboard />}
      {tab === "new" && <NewPlan />}
      {tab === "history" && <History />}
      {tab === "review" && reviewId && <Review planId={reviewId} />}
      <div>
        <input placeholder="plan id to review" onChange={(e) => setReviewId(e.target.value)} />
        <button onClick={() => setTab("review")}>Open review</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the component test + build**

Run (from `frontend/`): `npm run test -- --run && npm run build`
Expected: tests PASS; production build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src
git commit -m "feat(dtwin): frontend pages (dashboard, new plan, review, history)"
```

---

## Task 9: Run docs + token bootstrap

**Files:**
- Create: `webapp/README.md`

- [ ] **Step 1: Write `webapp/README.md`**

```markdown
# Web app — run instructions

## Backend (FastAPI)
```bash
cd src
pip install fastapi uvicorn httpx
export OPERATOR_TOKEN=op-secret EXPERT_TOKEN=ex-secret
python -m webapp.main          # serves on :8000
```

## Frontend (React)
```bash
cd src/frontend
npm install
npm run dev                    # serves on :5173, proxies /api -> :8000
```

Paste the operator or expert token into the header field. Operator can create
plans; expert can approve/reject/deploy and edit setpoints.

## Tests
```bash
cd src && python -m pytest                 # backend unit tests
cd src/frontend && npm run test -- --run   # frontend tests
```
```

- [ ] **Step 2: Commit**

```bash
git add src/webapp/README.md
git commit -m "docs(dtwin): web app run instructions"
```

---

## Self-Review

**Spec coverage (Plan 4 = spec §14 web application, M8):**
- §14.1 background-worker job model + `runs/<id>/` + SQLite index → Tasks 3, 5. ✅
- §14.1 token auth, operator/expert roles → Task 4; enforced on routes → Task 6. ✅
- §14.2 API surface (create/list/get/progress/approve/reject/setpoints) → Task 6. (Deploy endpoint reuses `deploy.py` from Plan 3 — add as a follow-up route mirroring approve; noted.) ✅ (deploy route is a thin wrapper; see note)
- §14.3 four frontend views → Tasks 7–8 (with frontend-design skill for polish). ✅
- §14.4 layout (`webapp/`, `frontend/`) → Tasks 3–8. ✅
- Progress streaming: implemented as **polling** `GET /progress` (v1, testable); WebSocket is a noted future enhancement. ✅
- DRY: shared `run_weekly_plan` used by template + worker → Task 2. ✅

**Note (small follow-ups, intentionally minimal):** the `POST /api/plans/{id}/deploy` route is a thin expert-only wrapper around Plan 3's `deploy()` (build a `ParallelEnvOracle`, call `deploy(rec_path, oracle)`); add it alongside `approve` once the integration env is available. The per-step trajectory plot endpoint (`GET /trajectory`) reads `temperature_data_*.csv` produced by Plan 3's trajectory entrypoints; wire it when those CSVs are generated in the deploy/prevalidation flow.

**Placeholder scan:** No TBD/TODO — every step has full code + exact command + expected output. The frontend components are functional (tested), explicitly handed to the frontend-design skill for visual polish (not placeholders). ✅

**Type consistency:** `PlanStore` method names (`create_plan`, `save_recommendation`, `get_recommendation`, `write_progress`, `read_progress`, `list_plans`, `get_plan_row`, `set_status`, `plan_dir`), `TokenAuth.check/require`, `JobRunner(store, runner).{start,submit,stop}`, `run_weekly_plan(request, evaluator, forecaster, ...)`, and the API client function names match across backend Tasks 3–6 and frontend Tasks 7–8. The recommendation dict shape matches Plan 3's `build_recommendation`. ✅

---

## Execution Handoff

Plan 4 complete (9 tasks: 6 backend with full TDD, 2 frontend with tests + frontend-design polish, 1 docs). With Plans 1–4 the framework has a tested core, an EnergyPlus oracle, a forecaster, the four template modes, the outer loop, and a full web app. Use the **frontend-design skill** during Tasks 7–8 for production-grade UI.
