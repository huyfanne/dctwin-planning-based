# SSE Progress Stream — Design Spec (sub-project C)

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope tier:** LATER **sub-project C** (operational polish). The last non-parked LATER item.
- **Predecessor specs (merged):** NOW, NEXT, LATER A (learning loop), LATER B (time-block).

---

## 1. Context & problem statement

The New-Plan page polls `GET /api/plans/{id}/progress` **and** `GET /api/plans/{id}` every 2 s while an
optimization runs (`NewPlan.tsx` `setInterval`). The original design §14.2 called for a real-time
**push** progress channel ("WS /api/plans/{id}/progress"). This sub-project delivers a real-time stream
that replaces the client-side polling with a single persistent connection.

**Decision (locked in brainstorming): Server-Sent Events (SSE) + a server-side file-poll**, not WebSocket.
Progress is one-way (server→client), so SSE is the better fit (native `EventSource`, auto-reconnect, no WS
upgrade). The `JobRunner` is a sync daemon thread writing `progress.json`; rather than bridge thread→async
(an `asyncio.Queue` + `call_soon_threadsafe`), the SSE generator simply reads `progress.json` + the status
row every ~500 ms server-side and streams changes — eliminating *client* polling while keeping the
server-side read cheap (a local file) and avoiding threaded↔async coordination.

## 2. Goals / non-goals

**Goals**
- `GET /api/plans/{id}/stream` SSE endpoint that pushes `{progress, status}` frames as a plan runs and
  closes when the plan reaches a terminal status (or a defensive cap / client disconnect).
- New-Plan subscribes via `EventSource` instead of polling; same UX (progress bar, evals, best-score,
  done/failed states).
- Auth that works with `EventSource` (which cannot set headers).

**Non-goals**
- WebSocket transport; the true thread→async event bridge (server-side poll is enough at per-level cadence).
- Streaming on History/Review (one-shot GETs are fine there); SSE for the deploy job (plan progress only).
- Removing `GET /progress` (kept as an additive fallback).

## 3. Decisions locked during brainstorming

| Question | Decision |
|---|---|
| Transport | **SSE** (`text/event-stream`), not WebSocket. |
| Push mechanism | **Server-side poll** of `progress.json` + status every ~500 ms; no thread→async bridge. |
| Auth | **`token` query param** validated by reusing `TokenAuth.check(f"Bearer {token}", "operator")` (EventSource can't send headers). |
| `GET /progress` | **Kept** as an additive fallback. |

## 4. Component design

### 4.1 Backend SSE endpoint (`webapp/main.py`, `webapp/store.py`)

Two pure **module-level** helpers in `webapp/main.py` (outside `create_app`, so tests can
`from webapp.main import is_terminal, progress_frame` without building the app):
- `is_terminal(status: str) -> bool` — `status not in {"queued", "running", "deploying"}`.
- `progress_frame(store, plan_id) -> dict` — `{"progress": store.read_progress(plan_id),
  "status": (store.get_plan_row(plan_id) or {}).get("status")}`.

The endpoint:

```python
@app.get("/api/plans/{plan_id}/stream")
async def stream_plan(plan_id: str, request: Request, token: str = ""):
    auth.check(f"Bearer {token}", "operator")          # reuse existing bearer validation (raises 401/403)
    if store.get_plan_row(plan_id) is None:
        raise HTTPException(404, "plan not found")

    async def gen():
        last = None
        for _ in range(600):                           # defensive cap ~5 min at 0.5 s
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

(`auth.check` already raises `HTTPException(401/403)` on a missing/invalid token or insufficient role, so a
bad `token` query rejects before streaming.)

### 4.2 Frontend (`frontend/src/pages/NewPlan.tsx`, `frontend/src/api.ts`)

- `api.ts`: a tiny helper `planStreamUrl(id) -> string` returning `/api/plans/${id}/stream?token=${TOKEN}`
  (so the token lives next to the other API plumbing, not inlined in the page).
- `NewPlan.tsx`: replace the `setInterval`/`getProgress`/`getPlan` poll loop with a single `EventSource`:
  - on `planId` set, open `new EventSource(planStreamUrl(planId))`;
  - `onmessage` → `JSON.parse(e.data)` → `setProgress(frame.progress)`, `setStatus(frame.status)`; if
    `frame.status` is terminal and not `failed`, `setDone(true)` and `es.close()`; if `failed`, set the
    existing error message and `es.close()`;
  - `onerror` → close + show the existing "backend/Docker" error UX (mirrors today's failed path);
  - cleanup closes the `EventSource` on unmount / "Start New Plan".
- History/Review unchanged.

## 5. Data-contract changes

- New endpoint `GET /api/plans/{id}/stream?token=…` → `text/event-stream`; each frame `data: {"progress":
  {level,evals,best_score}, "status": "<status>"}`.
- No schema/store changes; `GET /progress` and `GET /{id}` unchanged.

## 6. Error handling

- Missing/invalid `token` → 401; insufficient role → 403 (both from `auth.check`, before streaming).
- Unknown plan → 404.
- Client disconnect → the generator stops (`request.is_disconnected()`); defensive 600-iteration cap closes
  a stuck stream.
- Frontend `onerror` (network drop / server close) → close the connection and surface the error; the user
  can retry via the existing "Start New Plan" control. (EventSource would otherwise auto-reconnect; we
  close on terminal/`failed` to avoid a reconnect loop after the run ends.)

## 7. Testing strategy

**Backend unit:** `is_terminal` accept/reject table; `progress_frame` shape from a seeded store; the
endpoint via `TestClient` against a plan already in a **terminal** status (so the generator emits one frame
and returns — assert `200`, `content-type: text/event-stream`, and the body contains a `data:` line whose
JSON carries the right status); the stream **401s** with a missing/bad `token`.

**Frontend (vitest):** a mocked `EventSource` (jsdom lacks it) installed on `globalThis`; assert `NewPlan`
opens the stream, updates the progress bar/evals/status from a dispatched `message` event, marks done +
closes on a terminal frame, and shows the error path on `onerror`.

**No new Docker tests.**

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **C1** | `is_terminal` + `progress_frame` helpers (+ unit tests) | pure logic |
| **C2** | `GET /api/plans/{id}/stream` SSE endpoint (+ TestClient + auth tests) | the stream |
| **C3** | `api.ts planStreamUrl` + `NewPlan.tsx` EventSource (replace polling) + vitest | the UI |

## 9. Reference file index

- Backend: `webapp/main.py` (the endpoint + helpers; imports `asyncio`, `json`, `Request`,
  `StreamingResponse`), `webapp/store.py` (`read_progress`, `get_plan_row`), `webapp/auth.py`
  (`TokenAuth.check`), `webapp/status.py` (terminal status vocabulary reference).
- Frontend: `frontend/src/api.ts` (`planStreamUrl`, `TOKEN`), `frontend/src/pages/NewPlan.tsx`
  (`EventSource`), `frontend/src/pages/NewPlan.test.tsx`.
