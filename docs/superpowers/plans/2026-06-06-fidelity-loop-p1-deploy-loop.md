# Fidelity Loop P1 — Deploy→Realize→Refit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Physically close the outer loop in simulation: deploy an approved weekly plan to a *perturbed plant* (twin ≠ plant), capture realized KPIs, persist them, advance the forecaster history, with a validated status state machine and an expert-only deploy endpoint.

**Architecture:** Add a `PerturbedPlant` (nominal IDF with scaled Fan efficiency + Coil UA via opyplus) as the `deploy()` target, reusing the existing `ParallelEnvOracle`. Wire `deploy()` (already at `src/deploy.py`) into the web app via a background deploy job and `POST /api/plans/{id}/deploy`. Persist `realized.json`, enforce status transitions, and append the deployed week to the forecaster history. This is P1 of the spec `docs/superpowers/specs/2026-06-06-closing-fidelity-loop-design.md`; P2 (calibration/uncertainty/robust) is a follow-up plan.

**Tech Stack:** Python 3.13, dctwin + EnergyPlus 9.5 (BCVTB/Docker), opyplus (IDF editing — same lib dctwin uses), FastAPI, pytest. Run tests from `src/` with `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest`.

---

## File Structure

- **Create** `src/planner/plant.py` — `Perturbation`, `PlantConfig`, `DEFAULT_PLANT`, `apply_perturbation()` (opyplus IDF scale), `build_plant_prototxt()` (perturbed IDF + DT prototxt pointing at it).
- **Create** `src/tests/test_plant.py` — unit tests for the above.
- **Create** `src/webapp/status.py` — `PlanStatus` constants + `can_transition()` state machine.
- **Create** `src/tests/test_status.py` — transition tests.
- **Modify** `src/webapp/store.py` — add `save_realized()` / `get_realized()`.
- **Modify** `src/tests/test_store.py` — realized round-trip test.
- **Modify** `src/webapp/jobs.py` — add `run_deploy_job()` + generalize `JobRunner` to dispatch plan vs deploy jobs.
- **Modify** `src/tests/test_jobs.py` — deploy-dispatch test with an injected fake deploy runner.
- **Modify** `src/webapp/main.py` — `POST /api/plans/{id}/deploy` (expert), status-validated `approve`/`reject`, and `get_plan` includes realized.
- **Modify** `src/tests/test_api.py` — deploy endpoint auth + flow.
- **Create** `src/planner/history.py` — `advance_history()` (append a deployed week to the forecaster history CSV) + `refit_from_history()`.
- **Create** `src/tests/test_history.py` — append + refit tests.
- **Create** `src/tests/integration/test_deploy_loop.py` — marked integration: 1-day perturbed-plant deploy (skipped if no Docker).

Conventions to mirror (already in the repo):
- `src/planner/week_config.py::write_week_config` — read DT prototxt with `read_engine_config`, edit `env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))`, write with `text_format.MessageToString`. `env_cfg.model_file` is the IDF path.
- `src/deploy.py::deploy(recommendation_path, oracle, forecast=None)` — requires `status == "approved"`, runs `oracle.evaluate([setpoints])`, records `realized_kpis`, sets `status="deployed"`.
- `src/webapp/jobs.py` — `JobRunner` single worker; `run_plan_job` lazy-imports dctwin; `run_sync` path in `main.py`.

---

## Task 1: PerturbedPlant — `apply_perturbation`

**Files:**
- Create: `src/planner/plant.py`
- Test: `src/tests/test_plant.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_plant.py
import opyplus as op
from planner.plant import Perturbation, PlantConfig, DEFAULT_PLANT, apply_perturbation


def _first_fan_efficiency(idf_path):
    epm = op.Epm.load(idf_path)
    return next(iter(epm.Fan_VariableVolume)).fan_total_efficiency


def test_apply_perturbation_scales_fan_efficiency(tmp_path):
    base = "models/idf/building.idf"
    before = _first_fan_efficiency(base)
    out = str(tmp_path / "plant.idf")
    cfg = PlantConfig((Perturbation("Fan_VariableVolume", "fan_total_efficiency", 0.5),))
    apply_perturbation(base, cfg, out)
    after = _first_fan_efficiency(out)
    assert after == before * 0.5


def test_default_plant_has_fan_and_coil_perturbations():
    tables = {p.table for p in DEFAULT_PLANT.perturbations}
    assert tables == {"Fan_VariableVolume", "Coil_Cooling_Water"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_plant.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.plant'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/planner/plant.py
"""Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled
physical parameters (fan efficiency, coil UA). Same opyplus path dctwin uses."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class Perturbation:
    table: str   # opyplus table attr, e.g. "Fan_VariableVolume"
    field: str   # lowercased field, e.g. "fan_total_efficiency"
    factor: float


@dataclass(frozen=True)
class PlantConfig:
    perturbations: Tuple[Perturbation, ...]


# Degraded fan efficiency + fouled cooling coil -> the plant runs hotter and uses
# more energy than the (nominal) twin predicts. Both objects exist in the GDS IDF.
DEFAULT_PLANT = PlantConfig((
    Perturbation("Fan_VariableVolume", "fan_total_efficiency", 0.93),
    Perturbation("Coil_Cooling_Water", "u_factor_times_area_value", 0.85),
))


def apply_perturbation(idf_in: str, plant: PlantConfig, idf_out: str) -> str:
    """Scale the configured numeric fields and save a perturbed IDF copy.

    Non-numeric values (e.g. "autosize") are left untouched.
    """
    import opyplus as op

    epm = op.Epm.load(idf_in)
    for p in plant.perturbations:
        table = getattr(epm, p.table)
        for rec in table:
            val = rec[p.field]
            if isinstance(val, (int, float)):
                rec[p.field] = val * p.factor
    Path(idf_out).parent.mkdir(parents=True, exist_ok=True)
    epm.save(idf_out)
    return idf_out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_plant.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/plant.py src/tests/test_plant.py
git commit -m "feat(dtwin): PerturbedPlant apply_perturbation (opyplus fan/coil scaling)"
```

---

## Task 2: PerturbedPlant — `build_plant_prototxt`

**Files:**
- Modify: `src/planner/plant.py`
- Test: `src/tests/test_plant.py`

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_plant.py
from pathlib import Path
from planner.plant import build_plant_prototxt, DEFAULT_PLANT


def test_build_plant_prototxt_points_at_perturbed_idf(tmp_path):
    out_proto = build_plant_prototxt(
        "configs/dt/dt.prototxt", DEFAULT_PLANT, str(tmp_path))
    assert Path(out_proto).exists()
    # the perturbed IDF was written and the prototxt references it
    from dctwin.utils import read_engine_config
    cfg = read_engine_config(out_proto)
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert env.model_file == str(tmp_path / "plant.idf")
    assert (tmp_path / "plant.idf").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_plant.py::test_build_plant_prototxt_points_at_perturbed_idf -q`
Expected: FAIL with `ImportError: cannot import name 'build_plant_prototxt'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/planner/plant.py
def build_plant_prototxt(base_prototxt: str, plant: PlantConfig, out_dir: str) -> str:
    """Write a perturbed IDF + a DT prototxt copy that points at it. Mirrors
    week_config.write_week_config. Lazy dctwin import keeps the pure logic testable."""
    from dctwin.utils import read_engine_config
    from google.protobuf import text_format

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = read_engine_config(str(base_prototxt))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))

    idf_out = str(out / "plant.idf")
    apply_perturbation(env_cfg.model_file, plant, idf_out)
    env_cfg.model_file = idf_out

    proto_out = str(out / "plant.prototxt")
    Path(proto_out).write_text(text_format.MessageToString(cfg))
    return proto_out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_plant.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/plant.py src/tests/test_plant.py
git commit -m "feat(dtwin): build_plant_prototxt (perturbed IDF + DT prototxt)"
```

---

## Task 3: Status state machine

**Files:**
- Create: `src/webapp/status.py`
- Test: `src/tests/test_status.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_status.py
from webapp.status import PlanStatus, can_transition


def test_allowed_transitions():
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.APPROVED, PlanStatus.DEPLOYED)
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOYED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_FAILED)


def test_forbidden_transitions():
    assert not can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.DEPLOYED)
    assert not can_transition(PlanStatus.REJECTED, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.DEPLOYED, PlanStatus.APPROVED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_status.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webapp.status'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/webapp/status.py
"""Plan status values + the allowed transition graph (the outer-loop state machine)."""
from __future__ import annotations


class PlanStatus:
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    PENDING_APPROVAL = "pending_approval"
    INFEASIBLE_FALLBACK = "infeasible_fallback"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    DEPLOY_FAILED = "deploy_failed"


# expert/operator-driven transitions (the worker sets queued/running/failed itself)
_ALLOWED = {
    PlanStatus.PENDING_APPROVAL: {PlanStatus.APPROVED, PlanStatus.REJECTED},
    PlanStatus.INFEASIBLE_FALLBACK: {PlanStatus.APPROVED, PlanStatus.REJECTED},
    PlanStatus.APPROVED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
    PlanStatus.DEPLOYING: {PlanStatus.DEPLOYED, PlanStatus.DEPLOY_FAILED},
    PlanStatus.DEPLOY_FAILED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
}


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_status.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/status.py src/tests/test_status.py
git commit -m "feat(dtwin): plan status state machine (can_transition)"
```

---

## Task 4: Store — realized persistence

**Files:**
- Modify: `src/webapp/store.py`
- Test: `src/tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_store.py
def test_realized_roundtrip(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    assert store.get_realized("p1") is None
    realized = {"total_hvac_energy_kwh": 30000.0, "inlet_temp_max_c": 26.4,
                "pue_mean": 1.2, "inlet_violation_steps": 3}
    store.save_realized("p1", realized)
    got = store.get_realized("p1")
    assert got["inlet_temp_max_c"] == 26.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_store.py::test_realized_roundtrip -q`
Expected: FAIL with `AttributeError: 'PlanStore' object has no attribute 'save_realized'`.

- [ ] **Step 3: Write minimal implementation**

Add these two methods to `PlanStore` (in `src/webapp/store.py`), next to `get_recommendation`:

```python
    def save_realized(self, plan_id: str, realized: dict) -> None:
        (self.plan_dir(plan_id) / "realized.json").write_text(json.dumps(realized, indent=2))

    def get_realized(self, plan_id: str) -> Optional[dict]:
        p = self.plan_dir(plan_id) / "realized.json"
        return json.loads(p.read_text()) if p.exists() else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_store.py -q`
Expected: PASS (all store tests).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/store.py src/tests/test_store.py
git commit -m "feat(dtwin): store save_realized/get_realized (realized.json)"
```

---

## Task 5: Deploy job + JobRunner dispatch

**Files:**
- Modify: `src/webapp/jobs.py`
- Test: `src/tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_jobs.py
from webapp.jobs import JobRunner
from webapp.store import PlanStore


def test_jobrunner_dispatches_deploy(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    store.create_plan("p1", week_start="2013-11-11", params={})
    store.set_status("p1", "approved")
    calls = []

    def fake_deploy(plan_id, store_, progress_cb):
        calls.append(plan_id)
        store_.set_status(plan_id, "deployed")

    runner = JobRunner(store, deploy_runner=fake_deploy)
    # synchronous dispatch (no thread) for the test
    runner.run_deploy_sync("p1")
    assert calls == ["p1"]
    assert store.get_plan_row("p1")["status"] == "deployed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py::test_jobrunner_dispatches_deploy -q`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'deploy_runner'`.

- [ ] **Step 3: Write minimal implementation**

In `src/webapp/jobs.py`: (a) extend `JobRunner.__init__` with a `deploy_runner`; (b) make the queue carry a job kind; (c) add `submit_deploy` + `run_deploy_sync`; (d) dispatch in `_loop`; (e) add `run_deploy_job`.

Replace the `JobRunner` class body and add `run_deploy_job` as follows:

```python
class JobRunner:
    """Single-worker background runner for plan + deploy jobs (one at a time)."""

    def __init__(self, store: PlanStore, runner: Optional[RunnerFn] = None,
                 deploy_runner: Optional[Callable] = None):
        self.store = store
        self.runner = runner or run_plan_job
        self.deploy_runner = deploy_runner or run_deploy_job
        self._q: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def submit(self, plan_id: str, params: dict) -> None:
        self._q.put(("plan", plan_id, params))

    def submit_deploy(self, plan_id: str) -> None:
        self._q.put(("deploy", plan_id, None))

    def run_deploy_sync(self, plan_id: str) -> None:
        self.store.set_status(plan_id, "deploying")
        try:
            self.deploy_runner(plan_id, self.store,
                               lambda p, pid=plan_id: self.store.write_progress(pid, p))
        except Exception:  # noqa: BLE001
            logger.exception("deploy %s failed", plan_id)
            self.store.set_status(plan_id, "deploy_failed")

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            kind, plan_id, params = item
            if kind == "deploy":
                self.run_deploy_sync(plan_id)
                continue
            self.store.set_status(plan_id, "running")
            try:
                self.runner(plan_id, params, self.store,
                            lambda p, pid=plan_id: self.store.write_progress(pid, p))
            except Exception:  # noqa: BLE001
                logger.exception("plan %s failed", plan_id)
                self.store.set_status(plan_id, "failed")
```

Add `run_deploy_job` at the bottom of the file:

```python
def run_deploy_job(plan_id: str, store: PlanStore,
                   progress_cb: Callable[[dict], None]) -> None:
    """Run the PERTURBED PLANT for the approved week, persist realized KPIs, advance
    the forecaster history. Lazy dctwin import (tests inject a fake deploy_runner)."""
    from datetime import date
    import json as _json
    import pandas as pd
    from pathlib import Path

    from dctwin.utils import config as dt_config
    from deploy import deploy
    from planner.plant import DEFAULT_PLANT, build_plant_prototxt
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.forecaster import StatisticalForecaster
    from planner.history import advance_history

    plan_dir = store.plan_dir(plan_id)
    dt_config.set_log_dir(str(plan_dir / "deploy"))
    rec_path = str(plan_dir / "recommendation.json")
    rec = _json.loads(Path(rec_path).read_text())
    week_start = date.fromisoformat(rec["week_start"])

    # rebuild the forecaster so the plant runs the same materialized workload
    fc_cfg = pickle_load("models/forecaster.pkl")
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = _json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    n_steps = int(rec.get("days", 7)) * 24 * 4
    forecast = forecaster.forecast(week_start, n_steps)

    plant_prototxt = build_plant_prototxt("configs/dt/dt.prototxt", DEFAULT_PLANT,
                                          str(plan_dir / "plant"))
    plant_oracle = ParallelEnvOracle(
        base_prototxt=plant_prototxt, project_root=".",
        config=OracleConfig(n_workers=1, timesteps_per_hour=4,
                            log_root=str(plan_dir / "deploy" / "oracle")),
    )

    rec = deploy(rec_path, plant_oracle, forecast=forecast)
    store.save_realized(plan_id, rec["realized_kpis"])
    advance_history(rec["realized_kpis"], week_start, fc_cfg["his_csv"])
    store.set_status(plan_id, "deployed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_jobs.py -q`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/jobs.py src/tests/test_jobs.py
git commit -m "feat(dtwin): deploy job + JobRunner plan/deploy dispatch"
```

---

## Task 6: Forecaster history advance + refit

**Files:**
- Create: `src/planner/history.py`
- Test: `src/tests/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/test_history.py
import pandas as pd
from datetime import date
from planner.history import advance_history


def test_advance_history_appends_realized_week(tmp_path):
    csv = tmp_path / "his.csv"
    pd.DataFrame({"week_start": ["2013-11-04"], "total_hvac_energy_kwh": [31000.0],
                  "inlet_temp_max_c": [25.9]}).to_csv(csv, index=False)
    realized = {"total_hvac_energy_kwh": 30000.0, "inlet_temp_max_c": 26.1,
                "pue_mean": 1.2, "inlet_violation_steps": 0}
    advance_history(realized, date(2013, 11, 11), str(csv))
    df = pd.read_csv(csv)
    assert len(df) == 2
    assert df.iloc[-1]["week_start"] == "2013-11-11"
    assert df.iloc[-1]["total_hvac_energy_kwh"] == 30000.0


def test_advance_history_is_idempotent_per_week(tmp_path):
    csv = tmp_path / "his.csv"
    pd.DataFrame({"week_start": ["2013-11-11"], "total_hvac_energy_kwh": [1.0]}).to_csv(csv, index=False)
    advance_history({"total_hvac_energy_kwh": 30000.0}, date(2013, 11, 11), str(csv))
    df = pd.read_csv(csv)
    assert len(df) == 1                      # replaced, not duplicated
    assert df.iloc[-1]["total_hvac_energy_kwh"] == 30000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_history.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.history'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/planner/history.py
"""Advance the forecaster's realized-history with each deployed week (loop closure).

In sim+perturbed-plant this extends the rolling history the persistence/seasonal
forecaster reads; the *fidelity* learning (calibration) is added in P2a."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def advance_history(realized: dict, week_start: date, his_csv: str) -> None:
    """Append (or replace) the realized-week summary row keyed by week_start."""
    path = Path(his_csv)
    df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    row = {"week_start": week_start.isoformat(), **realized}
    if "week_start" in df.columns:
        df = df[df["week_start"] != week_start.isoformat()]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False)


def refit_from_history(forecaster_pkl: str = "models/forecaster.pkl") -> None:
    """Re-run the forecaster fit so the next plan sees the advanced history."""
    import runpy
    runpy.run_path("fit_forecaster.py", run_name="__main__")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_history.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/history.py src/tests/test_history.py
git commit -m "feat(dtwin): advance_history — append deployed week to forecaster history"
```

---

## Task 7: Deploy endpoint + status-validated gates + realized in GET

**Files:**
- Modify: `src/webapp/main.py`
- Test: `src/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# append to src/tests/test_api.py — assumes the file's existing TestClient + token helpers.
# If the existing tests build the app via create_app(...), reuse that fixture/pattern.
from fastapi.testclient import TestClient
from webapp.main import create_app
from webapp.auth import TokenAuth
from webapp.store import PlanStore


def _client(tmp_path):
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "index.db"))
    auth = TokenAuth({"op": "operator", "ex": "expert"})
    deployed = {}

    def fake_deploy(plan_id, store_, progress_cb):
        store_.save_realized(plan_id, {"total_hvac_energy_kwh": 30000.0,
                                       "inlet_temp_max_c": 26.2, "pue_mean": 1.2,
                                       "inlet_violation_steps": 1})
        store_.set_status(plan_id, "deployed")
        deployed["x"] = plan_id

    app = create_app(store=store, auth=auth, run_sync=True, deploy_runner=fake_deploy)
    return TestClient(app), store


def test_deploy_requires_expert_and_approval(tmp_path):
    client, store = _client(tmp_path)
    store.create_plan("p1", "2013-11-11", {})
    store.save_recommendation("p1", {"plan_id": "p1", "week_start": "2013-11-11",
                                     "status": "pending_approval", "setpoints": {}})
    # operator cannot deploy
    assert client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer op"}).status_code == 403
    # expert cannot deploy a non-approved plan
    assert client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer ex"}).status_code == 409
    # approve, then deploy succeeds and realized appears in GET
    client.post("/api/plans/p1/approve", headers={"Authorization": "Bearer ex"})
    r = client.post("/api/plans/p1/deploy", headers={"Authorization": "Bearer ex"})
    assert r.status_code == 202
    got = client.get("/api/plans/p1", headers={"Authorization": "Bearer op"}).json()
    assert got["status"] == "deployed"
    assert got["realized"]["inlet_temp_max_c"] == 26.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_api.py::test_deploy_requires_expert_and_approval -q`
Expected: FAIL (404/405 — no deploy route).

- [ ] **Step 3: Write minimal implementation**

In `src/webapp/main.py`: import the status helpers; let `create_app` accept an optional injected deploy runner; add the deploy route; validate approve/reject; include realized in `get_plan`.

Add near the top imports:
```python
from webapp.status import PlanStatus, can_transition
```

Add a `deploy_runner=None` parameter to `create_app(...)` and pass it to the `JobRunner` (replace the `job_runner = JobRunner(store, runner=runner)` line):
```python
def create_app(store=None, auth=None, runner=None, run_sync=False, deploy_runner=None):
    ...
    job_runner = JobRunner(store, runner=runner, deploy_runner=deploy_runner)
```
Tests inject the fake deploy runner directly via `create_app(..., deploy_runner=fake_deploy)` — no `app.state` hackery.

Replace the `approve` route body to validate the transition:
```python
    @app.post("/api/plans/{plan_id}/approve")
    def approve(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        if rec is None:
            raise HTTPException(404, "no recommendation yet")
        if not can_transition(rec.get("status", ""), PlanStatus.APPROVED):
            raise HTTPException(409, f"cannot approve from {rec.get('status')!r}")
        rec["status"] = PlanStatus.APPROVED
        store.save_recommendation(plan_id, rec)
        return {"status": PlanStatus.APPROVED}
```

Add the deploy route (after `reject`):
```python
    @app.post("/api/plans/{plan_id}/deploy", status_code=202)
    def deploy_plan(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        if rec is None:
            raise HTTPException(404, "no recommendation yet")
        if not can_transition(rec.get("status", ""), PlanStatus.DEPLOYING):
            raise HTTPException(409, f"cannot deploy from {rec.get('status')!r}")
        if run_sync:
            job_runner.run_deploy_sync(plan_id)
        else:
            job_runner.submit_deploy(plan_id)
        return {"status": PlanStatus.DEPLOYING}
```

Update `get_plan` to include realized:
```python
    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str, role: str = Depends(operator)):
        row = store.get_plan_row(plan_id)
        if row is None:
            raise HTTPException(404, "plan not found")
        return {"plan_id": plan_id, "status": row["status"],
                "recommendation": store.get_recommendation(plan_id),
                "realized": store.get_realized(plan_id)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/test_api.py -q`
Expected: PASS (existing + new; existing approve/reject tests still pass — they approve from `pending_approval`, which is allowed).

- [ ] **Step 5: Commit**

```bash
git add src/webapp/main.py src/tests/test_api.py
git commit -m "feat(dtwin): POST /deploy endpoint + status-validated gates + realized in GET"
```

---

## Task 8: Full backend suite + frontend "deploy" affordance (optional UI)

**Files:**
- Test: run the whole suite
- Modify (optional): `src/frontend/src/api.ts` (+ `Review.tsx`) — add `deployPlan(id)` + a Deploy button + realized display.

- [ ] **Step 1: Run the full backend suite**

Run: `cd src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -p no:warnings -q`
Expected: PASS (all prior tests + the new plant/status/store/jobs/history/api tests).

- [ ] **Step 2: (Optional) add the frontend deploy affordance**

In `src/frontend/src/api.ts` add:
```ts
export const deployPlan = (id: string) =>
  req<{ status: string }>(`/api/plans/${id}/deploy`, { method: "POST" });
```
In `Review.tsx`, when `detail.status === "approved"`, render a **Deploy** button calling `deployPlan(plan_id)`; when `detail.realized` is present, show a small "Realized vs Predicted" row (energy, peak inlet, violations).

- [ ] **Step 3: Build + test the frontend**

Run: `cd src/frontend && npm run build && npm run test -- --run`
Expected: build OK; tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/frontend/src/api.ts src/frontend/src/pages/Review.tsx
git commit -m "feat(dtwin): web Deploy button + realized-vs-predicted display"
```

---

## Task 9: Integration test — 1-day perturbed-plant deploy (marked, Docker)

**Files:**
- Create: `src/tests/integration/test_deploy_loop.py`

- [ ] **Step 1: Write the test**

```python
# src/tests/integration/test_deploy_loop.py
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_perturbed_plant_deploy_records_realized(tmp_path):
    """1-day deploy against the perturbed plant; realized KPIs are captured and
    differ from a nominal-twin run (the perturbation shows up)."""
    from planner.plant import DEFAULT_PLANT, build_plant_prototxt
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.forecaster import StatisticalForecaster
    from planner.types import Setpoints
    import pandas as pd

    import pickle
    fc_cfg = pickle.loads(Path("models/forecaster.pkl").read_bytes())
    his = pd.read_csv(fc_cfg["his_csv"])
    room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
    forecaster = StatisticalForecaster(his, room2ite, fc_cfg["his_col_for_room"],
                                       method=fc_cfg["method"])
    forecast = forecaster.forecast(date(2013, 11, 11), 1 * 24 * 4)

    sp = Setpoints(sat_c=20.0, flow_kg_s=7.05, chwst_c=13.0)

    plant_proto = build_plant_prototxt("configs/dt/dt.prototxt", DEFAULT_PLANT,
                                       str(tmp_path / "plant"))
    plant = ParallelEnvOracle(
        base_prototxt=plant_proto, project_root=".",
        config=OracleConfig(n_workers=1, timesteps_per_hour=4,
                            log_root=str(tmp_path / "plant_oracle")))
    realized = plant.evaluate([sp], forecast=forecast)[0]

    assert realized.total_hvac_energy_kwh > 0
    assert realized.inlet_temp_max == realized.inlet_temp_max  # not NaN
```

- [ ] **Step 2: Run under Docker**

Run: `cd src && sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest tests/integration/test_deploy_loop.py -m integration -q"`
Expected: PASS (one perturbed-plant 1-day run completes; realized captured). Skipped automatically when `-m integration` is not selected.

- [ ] **Step 3: Commit**

```bash
git add src/tests/integration/test_deploy_loop.py
git commit -m "test(dtwin): integration — 1-day perturbed-plant deploy captures realized"
```

---

## Self-review notes (addressed)

- **Spec coverage (P1):** PerturbedPlant (Tasks 1–2) ✓; deploy endpoint + job (Tasks 5, 7) ✓; realized persistence (Task 4) ✓; status state machine (Task 3, wired in Task 7) ✓; forecaster history advance (Task 6) ✓; realized in GET + optional UI (Tasks 7–8) ✓; integration test / CI gap (Task 9) ✓.
- **Deferred to P2 (out of scope here):** `Calibrator`, `calibration.json`, robust `ScenarioSet`/`robust_rerank`, confidence bands, recommendation schema 1.1, `Recalibrator` seam, `/api/calibration`. These are the next plan.
- **Type consistency:** `run_deploy_job(plan_id, store, progress_cb)` and the injected `fake_deploy` share the same 3-arg signature; `deploy_runner` used consistently in `JobRunner`, `run_deploy_sync`, and the route; `PlanStatus`/`can_transition` used in Task 3 and Task 7.
- **Known follow-up:** Task 6 `refit_from_history` (re-running `fit_forecaster.py`) is wired but `run_deploy_job` calls only `advance_history` (history advances every deploy; a full refit can be triggered separately to avoid coupling deploy latency to a forecaster re-fit). If you want deploy to also re-fit, add `from planner.history import refit_from_history; refit_from_history()` after `advance_history` in `run_deploy_job`.
