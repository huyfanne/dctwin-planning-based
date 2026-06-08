# Cancel a Running Plan — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope:** Backend (`webapp/jobs.py`, `webapp/status.py`, `webapp/main.py`) + frontend (`api.ts`, `NewPlan.tsx`, `History.tsx`).

---

## 1. Problem statement

A plan runs in the `JobRunner`'s single background thread inside the uvicorn process. There is no way to
stop it from the UI — killing the `ProcessPoolExecutor` workers doesn't work (the planner spawns a fresh pool
each batch), so the only way observed to stop a plan was to bounce the whole backend. Operators need a
**Cancel** button that stops a running (or queued) plan cleanly, leaving the webapp up.

**Chosen approach (locked in brainstorming): cooperative cancellation + container teardown.** A cancel sets a
per-plan flag the planner checks after each candidate, AND tears down the in-flight EnergyPlus containers so a
hung batch unblocks immediately.

## 2. Goals / non-goals

**Goals**
- `POST /api/plans/{id}/cancel` requests cancellation of a `queued`/`running` plan; the plan ends in a new
  terminal **`cancelled`** status, and the backend keeps serving.
- A hung batch cancels promptly (container teardown), not only after the per-candidate socket timeout.
- A **Cancel** button on the New-Plan live panel and on running/queued History rows.

**Non-goals**
- Cancelling a `deploying` plan (deploy is fast/rare) — 409.
- Per-plan container targeting (one plan runs at a time, so killing all E+ containers is correct).
- Distinguishing *why* it was cancelled, or cancel analytics.

## 3. The cancellation mechanism (key design)

The clean insight: the cancel check lives in the **`progress_cb`** that `_loop` builds and passes to the
runner. `run_plan_job`'s `on_eval(done)` already calls `progress_cb(dict(state))` **after each candidate**
(jobs.py:56-58), so making `progress_cb` raise on the flag propagates out with no change to the runner
signature and no impact on the existing fake runners (which also call `progress_cb`).

### 3.1 `webapp/jobs.py`

```python
class PlanCancelled(Exception):
    """Raised cooperatively (from progress_cb) when an operator cancels a running plan."""
```

`JobRunner.__init__` gains:
```python
self._cancel: set[str] = set()
self._cancel_lock = threading.Lock()
self._container_teardown = container_teardown or _kill_eplus_containers   # injectable for tests
```

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

Module-level best-effort container teardown (guarded; never raises):
```python
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

`_loop` changes (the plan branch):
```python
            kind, plan_id, params = item
            if kind == "deploy":
                self.run_deploy_sync(plan_id); continue
            if self._is_cancelled(plan_id):                 # queued-cancel: never started
                self._clear_cancel(plan_id)
                self.store.set_status(plan_id, "cancelled"); continue
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

`PlanCancelled` is checked **before** the generic `except`, so a cancel is not mis-recorded as a failure.
(`on_eval` fires per candidate → `progress_cb` raises → propagates out of `run_weekly_plan` → caught here.
For a hung batch, the container teardown makes the stuck candidates complete, which fires `on_eval`.)

### 3.2 `webapp/status.py`

Add `CANCELLED = "cancelled"` to `PlanStatus`. No `_ALLOWED` entry needed — the worker sets it directly via
`set_status` (like `running`/`failed`), and it's terminal, so `main.is_terminal` (status not in
queued/running/deploying) and `reconcile_orphans` treat it correctly with no change.

### 3.3 `webapp/main.py` — the endpoint

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

Operator-min (matches the other action routes). Registered with the other `/api/plans/...` routes (before the
static-frontend mount).

## 4. Frontend

- **`api.ts`:** `export const cancelPlan = (id: string) => req(`/api/plans/${id}/cancel`, { method: "POST" });`
- **`NewPlan.tsx`:** while `planId` is set and the run is live (`status` ∈ {`queued`,`running`} and not
  `done`/`error`), show a **Cancel** button → `cancelPlan(planId)` (disable + show "Cancelling…" after
  click). The SSE stream then delivers a `cancelled` frame; `onmessage` handles `status === 'cancelled'` →
  show a "Plan cancelled" state (not the done/Review state) + the Start-New-Plan control.
- **`History.tsx`:** for rows with status `queued`/`running`, a **Cancel** action → `cancelPlan(id)` → refresh
  the list; render a `cancelled` badge for cancelled plans (alongside the existing status badges).

## 5. Data flow

1. Operator clicks Cancel → `POST /cancel` → `request_cancel(id)`: flag set + E+ containers killed.
2. The stuck/active batch's candidates complete (teardown unblocks hung ones) → `on_eval` → `progress_cb`
   raises `PlanCancelled` → unwinds → `_loop` sets `cancelled`.
3. The SSE frame reports `status: "cancelled"` (terminal) → New-Plan shows "Plan cancelled"; History shows the
   badge. The `JobRunner` is free for the next job (the broken pool is per-evaluate, discarded).
4. A **queued** plan that's cancelled is marked `cancelled` at dequeue without running.

## 6. Error handling

- Cancel on an unknown plan → 404; on a non-`queued`/`running` plan → 409 (idempotent-ish: a second cancel of
  an already-terminal plan 409s).
- `_kill_eplus_containers` is fully guarded — a missing docker SDK / socket never breaks cancellation; the
  cooperative flag still stops the plan at the next candidate (just less promptly).
- The cancel flag is always cleared in `_loop`'s `finally`, so a stale flag can't poison a later same-id run
  (ids are unique per plan anyway).

## 7. Testing strategy

**Backend (pytest, no docker):**
- `JobRunner` with an injected `container_teardown` mock + a fake runner that calls `progress_cb` in a loop:
  `request_cancel` → the next `progress_cb` raises `PlanCancelled` → status `cancelled`, and the teardown mock
  was called. (Drive `_loop` via `submit` + a short wait, or call the cancel path directly.)
- Queued-cancel: cancel before the runner runs → status `cancelled`, runner never invoked.
- A normal failure still records `failed` (PlanCancelled-vs-Exception ordering preserved).
- Endpoint: `202` for a running plan (request_cancel called), `404` unknown, `409` for a terminal plan.

**Frontend (vitest):** the Cancel button shows while running, calls `cancelPlan`, and a `cancelled` SSE frame
renders the cancelled state (mock `EventSource` per the existing pattern); History shows Cancel on a running
row and calls `cancelPlan`.

**Build:** `npm run build` clean (`noUnusedLocals`).

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **C1** | `status.CANCELLED` + `jobs.PlanCancelled` + `_kill_eplus_containers` + `request_cancel`/cancel wiring in `_loop` (+ tests) | the cancel engine |
| **C2** | `POST /api/plans/{id}/cancel` (+ 202/404/409 tests) | the endpoint |
| **C3** | `api.ts cancelPlan` + `NewPlan` Cancel button + cancelled state (+ vitest) | the New-Plan UX |
| **C4** | `History` Cancel action + cancelled badge (+ vitest) | the History UX |

## 9. Reference file index

- `webapp/jobs.py` (`JobRunner.__init__`/`_loop`/`run_plan_job` on_eval at :56; add `PlanCancelled`,
  `request_cancel`, `_kill_eplus_containers`, the cancel-aware `progress_cb`).
- `webapp/status.py` (`PlanStatus`; add `CANCELLED`).
- `webapp/main.py` (action routes; add `POST …/cancel`).
- `frontend/src/api.ts` (`cancelPlan`), `frontend/src/pages/NewPlan.tsx` (Cancel button + cancelled frame),
  `frontend/src/pages/History.tsx` (Cancel action + badge).
