# SSE Progress Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the New-Plan 2-second GET polling with a Server-Sent Events stream that pushes `{progress, status}` frames from a single persistent connection until the plan reaches a terminal status.

**Architecture:** A `GET /api/plans/{id}/stream` SSE endpoint whose async generator server-side-polls `progress.json` + the status row every ~500 ms and yields on change; `?token=` query auth (EventSource can't send headers) reusing `TokenAuth.check`. The frontend swaps its `setInterval` poll for a browser `EventSource`. `GET /progress` stays as a fallback.

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), FastAPI/Starlette `StreamingResponse`, pytest `TestClient`; React 19 + Vite + vitest (`EventSource`). No Docker.

**Spec:** `docs/superpowers/specs/2026-06-07-sse-progress-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`
- The sandbox strips a leading `cd` — prefix with `env -C <dir>`.
- Python tests: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest <path> -v`. Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test ...` and `npm run build`.
- Commit after each task (repo policy appends a `Co-Authored-By` trailer — keep it). Branch `feat/sse-progress` (already created); do NOT switch branches.

---

## File map

| File | Change | Task |
|---|---|---|
| `webapp/main.py` | `is_terminal`/`progress_frame` helpers; `GET /api/plans/{id}/stream` SSE endpoint | 1, 2 |
| `frontend/src/api.ts` | `planStreamUrl(id)` | 3 |
| `frontend/src/pages/NewPlan.tsx` | `EventSource` replaces the poll loop | 3 |
| `frontend/src/pages/NewPlan.test.tsx` | mocked `EventSource` + updated/added tests | 3 |

---

## Task 1: `is_terminal` + `progress_frame` helpers (spec §4.1, C1)

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_is_terminal_table():
    from webapp.main import is_terminal
    assert is_terminal("pending_approval") and is_terminal("approved") and is_terminal("deployed")
    assert is_terminal("failed") and is_terminal("blocked_unsafe") and is_terminal("infeasible_fallback")
    assert not is_terminal("queued") and not is_terminal("running") and not is_terminal("deploying")


def test_progress_frame_shape(tmp_path):
    from webapp.main import progress_frame
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2013-11-11", {})
    store.write_progress("p1", {"level": 1, "evals": 5, "best_score": 0.9})
    frame = progress_frame(store, "p1")
    assert frame == {"progress": {"level": 1, "evals": 5, "best_score": 0.9}, "status": "queued"}
    assert progress_frame(store, "nope") == {"progress": {}, "status": None}
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k "is_terminal or progress_frame" -v`
Expected: FAIL — `cannot import name 'is_terminal'` / `'progress_frame'`.

- [ ] **Step 3: Add the module-level helpers**

In `webapp/main.py`, add at module level (after the imports, BEFORE `def create_app`):

```python
_RUNNING = {"queued", "running", "deploying"}


def is_terminal(status) -> bool:
    """A plan is terminal once it leaves the queued/running/deploying states."""
    return status not in _RUNNING


def progress_frame(store, plan_id: str) -> dict:
    """One SSE frame: the latest progress + the plan's current status."""
    row = store.get_plan_row(plan_id)
    return {"progress": store.read_progress(plan_id),
            "status": (row or {}).get("status")}
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k "is_terminal or progress_frame" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/main.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): is_terminal + progress_frame helpers for the SSE progress stream"
```

---

## Task 2: SSE stream endpoint (spec §4.1, C2)

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (reuses the `client` fixture + `_op()` header helper):

```python
def test_stream_endpoint_emits_a_frame_for_a_terminal_plan(client):
    # the fixture's fake_runner saves a recommendation + sets status 'pending_approval' (terminal),
    # so the SSE generator emits one frame and closes — TestClient can read the full body.
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    r = client.get(f"/api/plans/{pid}/stream?token=op")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "data:" in r.text
    # the streamed frame carries the terminal status
    import json as _json
    payload = _json.loads(r.text.split("data:", 1)[1].split("\n\n", 1)[0].strip())
    assert payload["status"] == "pending_approval"


def test_stream_endpoint_rejects_bad_token(client):
    pid = client.post("/api/plans", json={"week_start": "2013-11-11"}, headers=_op()).json()["plan_id"]
    assert client.get(f"/api/plans/{pid}/stream?token=nope").status_code == 401
    assert client.get(f"/api/plans/{pid}/stream").status_code == 401          # missing token


def test_stream_endpoint_404_unknown_plan(client):
    assert client.get("/api/plans/does-not-exist/stream?token=op").status_code == 404
```

(The `client` fixture uses `TokenAuth({"op": "operator", "ex": "expert"})` and `run_sync=True` with a
`fake_runner` that calls `store.save_recommendation` with `status="pending_approval"` — so a freshly
created plan is already terminal, the generator emits one frame and returns, and `TestClient` doesn't hang.)

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k stream -v`
Expected: FAIL — `404` for the stream path (endpoint not defined yet → FastAPI returns 404 for all three; assertions on body/200 fail).

- [ ] **Step 3: Add the imports + the endpoint**

In `webapp/main.py`, extend the imports at the top:

```python
import asyncio
import json
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
```

Inside `create_app`, add the endpoint (place it right after the existing `get_progress` route):

```python
    @app.get("/api/plans/{plan_id}/stream")
    async def stream_plan(plan_id: str, request: Request, token: str = ""):
        # EventSource can't send headers, so the bearer rides in ?token=; reuse the existing check.
        auth.check(f"Bearer {token}", "operator")
        if store.get_plan_row(plan_id) is None:
            raise HTTPException(404, "plan not found")

        async def gen():
            last = None
            for _ in range(600):                       # defensive cap (~5 min at 0.5 s)
                if await request.is_disconnected():
                    break
                frame = progress_frame(store, plan_id)
                if frame != last:
                    yield f"data: {json.dumps(frame)}\n\n"
                    last = frame
                if is_terminal(frame["status"]):
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})
```

(`auth.check` raises `HTTPException(401)` on a missing/invalid token and `403` on an insufficient role —
so the bad-token cases reject before any streaming. A terminal plan yields exactly one frame then `break`s
before the first `sleep`, so the response completes immediately.)

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -v`
Expected: PASS (the 3 new stream tests + all existing api tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/main.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): GET /api/plans/{id}/stream SSE progress endpoint (query-token auth)"
```

---

## Task 3: Frontend EventSource (spec §4.2, C3)

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/NewPlan.tsx`
- Test: `frontend/src/pages/NewPlan.test.tsx`

- [ ] **Step 1: Add `planStreamUrl` to `api.ts`**

In `frontend/src/api.ts`, add after the existing exports (it uses the module's `TOKEN`):

```typescript
export const planStreamUrl = (id: string) => `/api/plans/${id}/stream?token=${encodeURIComponent(TOKEN)}`;
```

- [ ] **Step 2: Install a mocked `EventSource` + update the NewPlan tests**

`jsdom` has no `EventSource`, so the test installs a mock. In `frontend/src/pages/NewPlan.test.tsx`, add the mock class + `beforeEach` install (after the existing `vi.mock('../api', ...)` block) and add `planStreamUrl` to the api mock factory:

```typescript
// add to the existing vi.mock('../api', () => ({ ... })) factory:
//   planStreamUrl: (id: string) => `/api/plans/${id}/stream?token=t`,

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(url: string) { this.url = url; MockEventSource.instances.push(this); }
  close() { this.closed = true; }
  emit(frame: object) { this.onmessage?.({ data: JSON.stringify(frame) }); }
  fail() { this.onerror?.(); }
}

beforeEach(() => {
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource = MockEventSource;
});
```

**Also update the test's import line** (currently `import { createPlan, getProgress } from '../api';`, line 11): change it to `import { createPlan } from '../api';`. After the rewrite below `getProgress` is no longer referenced, and `tsconfig.app.json` has `noUnusedLocals: true` + `include: ["src"]` (so `.test.tsx` is type-checked) — leaving the import makes `npm run build`'s `tsc -b` (Step 5) fail with `TS6133: 'getProgress' is declared but its value is never read`. (Leave the `getProgress: vi.fn()` / `getPlan: vi.fn()` entries in the `vi.mock` factory object — object-literal properties are NOT flagged by `noUnusedLocals`.)

UPDATE the existing `it('creates plan and shows progress panel on submit', ...)` test: it currently relies on `getProgress` polling (a `(getProgress as ...).mockResolvedValue({...})` line). Replace the whole test body — drop that `getProgress` mock line and assert progress from an `EventSource` frame instead — after the plan id appears, push a frame and assert the progress shows:

```typescript
  it('creates plan and shows progress panel on submit', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p-new-1', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(screen.getByText('p-new-1')).toBeInTheDocument());
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { level: 1, evals: 42, best_score: 0.9 }, status: 'running' });
    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());   // evals tile (42 avoids the grid=5 default)
  });
```

Add two tests inside the `describe('NewPlan', ...)` block:

```typescript
  it('marks done on a terminal frame', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p2', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { level: 3, evals: 40 }, status: 'pending_approval' });
    await waitFor(() => expect(screen.getByText(/review results/i)).toBeInTheDocument());
  });

  it('shows an error when the stream errors', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p3', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].fail();
    // {error} renders in BOTH the form card AND the live-progress card once planId is set,
    // so use getAllByText (single-match getByText would throw on the duplicate).
    await waitFor(() => expect(screen.getAllByText(/lost connection|backend/i).length).toBeGreaterThan(0));
  });
```

- [ ] **Step 3: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- NewPlan`
Expected: FAIL — NewPlan still polls (no `EventSource` opened → `MockEventSource.instances.length` stays 0).

- [ ] **Step 4: Swap NewPlan polling for `EventSource`**

In `frontend/src/pages/NewPlan.tsx`:

(a) Imports: change line 2 to `import { createPlan, planStreamUrl, type Progress } from '../api';` (drop `getProgress`/`getPlan`).

(b) Remove `const POLL_MS = 2000;` and `const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);`. Add `const esRef = useRef<EventSource | null>(null);`.

(c) Replace the entire polling `useEffect` (the `useEffect(() => { if (!planId || done || error) return; pollRef.current = setInterval(...) ... }, [planId, done, error]);` block) with:

```tsx
  useEffect(() => {
    if (!planId || done || error) return;
    const es = new EventSource(planStreamUrl(planId));
    esRef.current = es;
    es.onmessage = (e) => {
      const frame = JSON.parse(e.data) as { progress: Progress; status: string };
      if (frame.progress) setProgress(frame.progress);
      setStatus(frame.status);
      if (frame.status === 'failed') {
        setError('Plan run failed on the server. Most likely the backend was not started with Docker access (sg docker) so EnergyPlus could not run — see the backend log.');
        es.close();
      } else if (frame.status && !['queued', 'running', 'deploying'].includes(frame.status)) {
        setDone(true);
        es.close();
      }
    };
    es.onerror = () => {
      es.close();
      setError('Lost connection to the progress stream. The backend may have stopped — see the backend log.');
    };
    return () => { es.close(); };
  }, [planId, done, error]);
```

(d) In the error-reset "Start New Plan" button handler, change `if (pollRef.current) clearInterval(pollRef.current);` to `esRef.current?.close();`. **Do step 4(c) first** — the string `if (pollRef.current) clearInterval(pollRef.current);` appears multiple times inside the old poll `useEffect`; once 4(c) has replaced that whole block, the only remaining occurrence is in this button handler, so the Edit target is then unique. (If matching is still ambiguous, include the surrounding `setPlanId(null);` line for context.)

(e) Update the status footer text (the `Status: {status} · polling every 2s…` line) to `Status: {status} · live stream`.

- [ ] **Step 5: Run the frontend tests + build**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass (incl. the 3 NewPlan tests); `tsc -b && vite build` clean (no unused-import TS errors — confirm `getProgress`/`getPlan`/`POLL_MS` are fully removed).

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/pages/NewPlan.tsx src/frontend/src/pages/NewPlan.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): New-Plan streams progress via EventSource (replaces 2s polling)"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test && npm run build`.
- [ ] Confirm `GET /api/plans/{id}/progress` still exists (fallback) and the new `GET /api/plans/{id}/stream` returns `text/event-stream`.
- [ ] Update memory (`dtwin-dual-loop-framework.md`) with sub-project C (SSE progress, query-token auth) — completes the non-parked LATER items.
