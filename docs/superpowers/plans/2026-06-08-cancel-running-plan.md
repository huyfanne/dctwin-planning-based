# Cancel a Running Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Cancel button that stops a running/queued plan cleanly (cooperative cancellation + EnergyPlus container teardown) without bouncing the backend, ending the plan in a new terminal `cancelled` status.

**Architecture:** The cancel-check rides the `progress_cb` that `JobRunner._loop` builds (which `run_plan_job`'s `on_eval` calls per candidate) → it raises `PlanCancelled`, caught in `_loop` → `set_status("cancelled")`. `request_cancel` also tears down in-flight E+ containers (best-effort, injectable) to unblock a hung batch. A `POST /api/plans/{id}/cancel` endpoint + Cancel buttons on New-Plan and History drive it.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), FastAPI/pytest `TestClient`; React 19 + Vite + vitest. No Docker in unit tests (teardown is mocked).

**Spec:** `docs/superpowers/specs/2026-06-08-cancel-running-plan-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`. The sandbox strips a leading `cd` — use `env -C <dir>`.
- Backend tests: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest <path> -v`. Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- <name>` and `npm run build`.
- Branch `feat/cancel-running-plan` (already created); do NOT switch branches. Commit after each task (repo appends a `Co-Authored-By` trailer — keep it).

---

## File map

| File | Change | Task |
|---|---|---|
| `webapp/status.py` | add `CANCELLED` | C1 |
| `webapp/jobs.py` | `PlanCancelled`, `_kill_eplus_containers`, `JobRunner` cancel wiring | C1 |
| `tests/test_jobs.py` | cancel-running + queued-cancel tests | C1 |
| `webapp/main.py` | `create_app` `container_teardown` param + `POST …/cancel` | C2 |
| `tests/test_api.py` | 202/404/409 endpoint tests | C2 |
| `frontend/src/api.ts` | `cancelPlan` | C3 |
| `frontend/src/pages/NewPlan.tsx` | Cancel button + `cancelled` frame/state | C3 |
| `frontend/src/pages/NewPlan.test.tsx` | Cancel + cancelled tests | C3 |
| `frontend/src/pages/History.tsx` | Cancel action + `cancelled` badge + refetch | C4 |
| `frontend/src/pages/History.test.tsx` | Cancel-on-running test | C4 |

---

## Task C1: cancel engine (jobs.py + status.py)

**Files:**
- Modify: `webapp/status.py`, `webapp/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jobs.py` (it already imports `JobRunner`, `time`, `PlanStore`, and has `_wait_status`):

```python
def test_request_cancel_stops_a_running_plan(tmp_path):
    import threading
    from unittest.mock import Mock
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    started = threading.Event()

    def looping_runner(plan_id, params, store, progress_cb):
        started.set()
        for _ in range(100000):
            progress_cb({"level": 0, "evals": 1})   # raises PlanCancelled once cancelled
            time.sleep(0.005)

    teardown = Mock()
    runner = JobRunner(store, runner=looping_runner, container_teardown=teardown)
    runner.start()
    try:
        runner.submit("p1", {})
        assert started.wait(2)
        _wait_status(store, "p1", "running")
        runner.request_cancel("p1")
        _wait_status(store, "p1", "cancelled")
        teardown.assert_called_once()       # in-flight containers torn down
    finally:
        runner.stop()


def test_request_cancel_skips_a_queued_plan(tmp_path):
    from unittest.mock import Mock
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    ran = []

    def runner_fn(plan_id, params, store, progress_cb):
        ran.append(plan_id)

    runner = JobRunner(store, runner=runner_fn, container_teardown=Mock())
    runner.request_cancel("p1")             # cancel BEFORE it is dequeued
    runner.submit("p1", {})
    runner.start()
    try:
        _wait_status(store, "p1", "cancelled")
        time.sleep(0.2)
        assert ran == []                    # never executed
    finally:
        runner.stop()
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -k "request_cancel" -v`
Expected: FAIL — `JobRunner.__init__() got an unexpected keyword argument 'container_teardown'` (and no `request_cancel`).

- [ ] **Step 3: Add `CANCELLED` to status.py**

In `webapp/status.py`, add to `class PlanStatus` (after `DEPLOY_BLOCKED`):

```python
    CANCELLED = "cancelled"                        # operator cancelled a running/queued plan
```

- [ ] **Step 4: Implement the cancel engine in jobs.py**

In `webapp/jobs.py`, add a module-level exception + teardown helper (near `pickle_load`/`record_failure`):

```python
class PlanCancelled(Exception):
    """Raised cooperatively (from progress_cb) when an operator cancels a running plan."""


def _kill_eplus_containers() -> None:
    """Kill running EnergyPlus containers so a hung batch unblocks. One plan runs at a time,
    so every E+ container belongs to the current plan. Best-effort — fully guarded."""
    try:
        import docker
        client = docker.from_env()
        for c in client.containers.list():
            if any("energyplus" in t.lower() for t in (c.image.tags or [])):
                try:
                    c.kill()
                except Exception:
                    pass
    except Exception:
        pass
```

In `JobRunner.__init__`, add the `container_teardown` parameter and cancel state (the current signature is `def __init__(self, store, runner=None, deploy_runner=None):`):

```python
    def __init__(self, store: PlanStore, runner: Optional[RunnerFn] = None,
                 deploy_runner: Optional[Callable] = None, container_teardown=None):
        self.store = store
        self.runner = runner or run_plan_job
        self.deploy_runner = deploy_runner or run_deploy_job
        self._q: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cancel: set[str] = set()
        self._cancel_lock = threading.Lock()
        self._container_teardown = container_teardown or _kill_eplus_containers
```

Add the cancel methods (anywhere in `JobRunner`, e.g. after `reconcile_orphans`):

```python
    def request_cancel(self, plan_id: str) -> None:
        with self._cancel_lock:
            self._cancel.add(plan_id)
        self._container_teardown()          # best-effort: unblock a hung batch immediately

    def _is_cancelled(self, plan_id: str) -> bool:
        with self._cancel_lock:
            return plan_id in self._cancel

    def _clear_cancel(self, plan_id: str) -> None:
        with self._cancel_lock:
            self._cancel.discard(plan_id)
```

Replace the plan branch of `_loop` (currently sets `"running"` then calls `self.runner(...)` with a `write_progress` lambda, with one `except Exception`) with:

```python
            if self._is_cancelled(plan_id):                 # queued-cancel: never started
                self._clear_cancel(plan_id)
                self.store.set_status(plan_id, "cancelled")
                continue
            self.store.set_status(plan_id, "running")

            def progress_cb(p, pid=plan_id):
                if self._is_cancelled(pid):
                    raise PlanCancelled()
                self.store.write_progress(pid, p)

            try:
                self.runner(plan_id, params, self.store, progress_cb)
            except PlanCancelled:
                logger.info("plan %s cancelled", plan_id)
                self.store.set_status(plan_id, "cancelled")
            except Exception as e:  # noqa: BLE001
                logger.exception("plan %s failed", plan_id)
                record_failure(self.store, plan_id, e)
            finally:
                self._clear_cancel(plan_id)
```

(The `if kind == "deploy": … continue` line above this stays unchanged. `PlanCancelled` is caught **before** the generic `except`, so a cancel is never recorded as a failure.)

- [ ] **Step 5: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -v`
Expected: PASS (2 new cancel tests + existing jobs tests, incl. `test_job_failure_sets_failed` — a generic exception still records `failed`).

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/status.py src/webapp/jobs.py src/tests/test_jobs.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): cooperative plan cancellation engine (PlanCancelled + container teardown)"
```

---

## Task C2: `POST /api/plans/{id}/cancel` endpoint

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_cancel_endpoint_running_404_409(tmp_path):
    from webapp.main import create_app
    store = PlanStore(runs_dir=str(tmp_path / "r"), db_path=str(tmp_path / "i.db"))
    store.create_plan("run", "2013-11-11", {});  store.set_status("run", "running")
    store.create_plan("term", "2013-11-11", {}); store.set_status("term", "pending_approval")
    app = create_app(store=store, auth=TokenAuth({"op": "operator"}), run_sync=True,
                     container_teardown=lambda: None)
    c = TestClient(app)
    assert c.post("/api/plans/run/cancel", headers=_op()).status_code == 202       # running -> cancellable
    assert c.post("/api/plans/term/cancel", headers=_op()).status_code == 409      # terminal -> no
    assert c.post("/api/plans/nope/cancel", headers=_op()).status_code == 404       # unknown
    assert c.post("/api/plans/run/cancel").status_code == 401                       # no token
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k cancel_endpoint -v`
Expected: FAIL — `create_app()` has no `container_teardown` kwarg (and no `/cancel` route → 404 for the 202 case).

- [ ] **Step 3: Thread `container_teardown` + add the endpoint**

In `webapp/main.py`, add the param to `create_app` and pass it to the `JobRunner` (current head: `def create_app(store=…, auth=…, runner=None, run_sync=False, deploy_runner=None, frontend_dist=None)` and `job_runner = JobRunner(store, runner=runner, deploy_runner=deploy_runner)`):

```python
def create_app(store: Optional[PlanStore] = None, auth: Optional[TokenAuth] = None,
               runner=None, run_sync: bool = False, deploy_runner=None,
               frontend_dist: Optional[str] = None, container_teardown=None) -> FastAPI:
    store = store or PlanStore()
    auth = auth or TokenAuth.from_env()
    job_runner = JobRunner(store, runner=runner, deploy_runner=deploy_runner,
                           container_teardown=container_teardown)
```

Add the route right after the `@app.post("/api/plans/{plan_id}/reject")` route:

```python
    @app.post("/api/plans/{plan_id}/cancel", status_code=202)
    def cancel_plan(plan_id: str, role: str = Depends(operator)):
        row = store.get_plan_row(plan_id)
        if row is None:
            raise HTTPException(404, "plan not found")
        if row["status"] not in ("queued", "running"):
            raise HTTPException(409, f"cannot cancel a {row['status']!r} plan")
        job_runner.request_cancel(plan_id)
        return {"status": "cancelling"}
```

- [ ] **Step 4: Run it, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -q`
Expected: PASS (the new cancel test + all existing api tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/main.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): POST /api/plans/{id}/cancel (202/404/409)"
```

---

## Task C3: New-Plan Cancel button + cancelled state

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/pages/NewPlan.tsx`
- Test: `frontend/src/pages/NewPlan.test.tsx`

- [ ] **Step 1: Add `cancelPlan` to `api.ts`**

In `frontend/src/api.ts`, add after `deployPlan`:

```ts
export const cancelPlan = (id: string) => req(`/api/plans/${id}/cancel`, { method: "POST" });
```

- [ ] **Step 2: Update the NewPlan tests (failing)**

In `frontend/src/pages/NewPlan.test.tsx`: add `cancelPlan: vi.fn(),` to the `vi.mock('../api', …)` factory, and change the import to `import { createPlan, getWeather, cancelPlan } from '../api';`. Then add two tests inside `describe('NewPlan', …)`:

```tsx
  it('shows Cancel while running and calls cancelPlan', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'pc', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2024-11-11' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { level: 1, evals: 5 }, status: 'running' });
    fireEvent.click(await screen.findByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(cancelPlan).toHaveBeenCalledWith('pc'));
  });

  it('shows the cancelled state on a cancelled frame', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'pc2', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2024-11-11' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: {}, status: 'cancelled' });
    await waitFor(() => expect(screen.getAllByText(/cancelled/i).length).toBeGreaterThan(0));
    expect(screen.queryByText(/review results/i)).not.toBeInTheDocument();
  });
```

- [ ] **Step 3: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- NewPlan`
Expected: FAIL — no Cancel button; a `cancelled` frame currently hits the generic terminal branch (`setDone`) so "Review Results" shows and there's no "cancelled" text.

- [ ] **Step 4: Implement in `NewPlan.tsx`**

(a) Import (line 2): `import { createPlan, planStreamUrl, getWeather, cancelPlan, type Progress } from '../api';`

(b) Add two state vars after `const [coverage, setCoverage] = useState<string | null>(null);`:

```tsx
  const [cancelled, setCancelled] = useState(false);
  const [cancelling, setCancelling] = useState(false);
```

(c) In the SSE effect, change the guard (line 41) to `if (!planId || done || error || cancelled) return;`, add `cancelled` to the dep array (line 77 → `}, [planId, done, error, cancelled]);`), and add a `cancelled` branch in `onmessage` (between the `failed` and the generic terminal branch):

```tsx
        if (frame.status === 'failed') {
          setError(frame.progress?.error ?? 'Plan run failed on the server — see the backend log (the backend may lack Docker access for EnergyPlus).');
          stopped = true; es.close();
        } else if (frame.status === 'cancelled') {
          setCancelled(true); stopped = true; es.close();
        } else if (frame.status && !['queued', 'running', 'deploying'].includes(frame.status)) {
          setDone(true); stopped = true; es.close();
        }
```

(d) In the Live-Progress card header badge (the `error ? Failed : done ? Complete : Running` ternary), add a cancelled case — replace it with:

```tsx
              {error ? <span className="badge" style={{ color: 'var(--amber, #f5a623)', borderColor: 'var(--amber, #f5a623)' }}>Failed</span>
                : cancelled ? <span className="badge badge-rejected">Cancelled</span>
                : done ? <span className="badge badge-approved">Complete</span>
                : <span className="live-dot">Running</span>}
```

(e) In the Action area, add a Cancel button while running and a cancelled block. Insert **before** the `{done && (` block:

```tsx
              {!done && !error && !cancelled && (
                <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}
                  disabled={cancelling}
                  onClick={async () => { setCancelling(true); try { await cancelPlan(planId!); } catch { /* stream reflects it */ } }}>
                  {cancelling ? 'Cancelling…' : 'Cancel Plan'}
                </button>
              )}
              {cancelled && (
                <>
                  <div className="error-msg">Plan cancelled.</div>
                  <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => {
                      esRef.current?.close();
                      setPlanId(null); setProgress(null); setDone(false); setCancelled(false);
                      setCancelling(false); setError(null); setStatus('queued'); setSubmitting(false);
                    }}>
                    ← Start New Plan
                  </button>
                </>
              )}
```

(f) The status footer guard (`{!done && !error && (`) → `{!done && !error && !cancelled && (` so the "live stream" line hides once cancelled.

- [ ] **Step 5: Run tests + build, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass (incl. the 2 new NewPlan tests); `tsc -b && vite build` clean (no unused-import/`noUnusedLocals` errors — `cancelPlan` is used).

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/pages/NewPlan.tsx src/frontend/src/pages/NewPlan.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): New-Plan Cancel button + cancelled state"
```

---

## Task C4: History Cancel action + cancelled badge

**Files:**
- Modify: `frontend/src/pages/History.tsx`
- Test: `frontend/src/pages/History.test.tsx`

- [ ] **Step 1: Update the History tests (failing)**

In `frontend/src/pages/History.test.tsx`: ensure the `vi.mock('../api', …)` factory includes `cancelPlan: vi.fn(),` and `listPlans` is imported; import `cancelPlan`. Add a test:

```tsx
  it('shows Cancel on a running plan and calls cancelPlan', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([
      { plan_id: 'r1', week_start: '2024-11-11', status: 'running', energy_kwh: null, reduction_pct: null },
    ]);
    render(<History onReview={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(cancelPlan).toHaveBeenCalledWith('r1'));
  });
```

(If `History.test.tsx` doesn't exist, create it with the standard header: `import { describe, it, expect, vi, beforeEach } from 'vitest';` + `import { render, screen, fireEvent, waitFor } from '@testing-library/react';` + `import History from './History';` + `vi.mock('../api', () => ({ listPlans: vi.fn().mockResolvedValue([]), cancelPlan: vi.fn() }));` + `import { listPlans, cancelPlan } from '../api';` + `beforeEach(() => vi.clearAllMocks());` then the `describe`.)

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- History`
Expected: FAIL — no Cancel button on the running row.

- [ ] **Step 3: Implement in `History.tsx`**

(a) Import (line 3): `import { listPlans, cancelPlan, type PlanSummary } from '../api';`

(b) Add a `cancelled` case to `statusClass` (before the final `return 'badge-running';`):

```tsx
  if (s === 'cancelled')     return 'badge-rejected';
```

(c) Extract the list fetch into a reusable `load()` so it can refetch after cancel. Replace the `useEffect(() => { listPlans()… }, [])` block with:

```tsx
  function load() {
    setLoading(true);
    listPlans()
      .then(setPlans)
      .catch(e => setError(e instanceof Error ? e.message : 'failed to load plans'))
      .finally(() => setLoading(false));
  }
  useEffect(() => { load(); }, []);
```

(d) In the row's last `<td>` (the one with the `Review →` button), add a Cancel button for queued/running plans, before the Review button:

```tsx
                      <td style={{ textAlign: 'right' }}>
                        {(p.status === 'running' || p.status === 'queued') && (
                          <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 12px', marginRight: 6 }}
                            onClick={async () => { try { await cancelPlan(p.plan_id); } finally { load(); } }}>
                            Cancel
                          </button>
                        )}
                        <button
                          className="btn btn-ghost"
                          style={{ fontSize: 11, padding: '4px 12px' }}
                          onClick={() => onReview(p.plan_id)}
                        >
                          Review →
```

(Leave the rest of that `<td>`/button unchanged.)

- [ ] **Step 4: Run tests + build, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass (incl. the new History test); build clean.

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/pages/History.tsx src/frontend/src/pages/History.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): History Cancel action + cancelled badge"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test && npm run build`.
- [ ] Manual sanity (optional): start a plan → New-Plan shows **Cancel Plan** → click → status flips to **Cancelled** (the SSE stream closes); History shows a **Cancel** on running rows and a `cancelled` badge after.
