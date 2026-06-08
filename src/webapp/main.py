from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from webapp.auth import TokenAuth
from webapp.jobs import JobRunner
from webapp.schemas import PlanCreated, PlanParams, SetpointEdit
from webapp.status import PlanStatus, can_transition
from webapp.store import PlanStore

_RUNNING = {"queued", "running", "deploying"}


def is_terminal(status) -> bool:
    """A plan is terminal once it leaves the queued/running/deploying states."""
    return status not in _RUNNING


def progress_frame(store, plan_id: str) -> dict:
    """One SSE frame: the latest progress + the plan's current status."""
    row = store.get_plan_row(plan_id)
    return {"progress": store.read_progress(plan_id),
            "status": (row or {}).get("status")}


_STREAM_POLL_S = 0.5
_STREAM_MAX_ITERS = 14400          # ~2 h backstop at 0.5 s — generous; a long plan won't be cut off
_STREAM_KEEPALIVE_EVERY = 30       # ~15 s: emit an SSE comment so the connection never looks idle/dead


async def plan_sse_stream(store, plan_id: str, is_disconnected, *, sleep=asyncio.sleep,
                          max_iters: int = _STREAM_MAX_ITERS,
                          keepalive_every: int = _STREAM_KEEPALIVE_EVERY):
    """Yield SSE chunks for a plan's progress until it turns terminal, the client
    disconnects, or the (generous) backstop is hit. During long no-progress stretches
    it emits a ``: keepalive`` comment every ``keepalive_every`` polls so proxies/clients
    don't drop an idle connection (the old 5-minute cap closed real, longer plans early)."""
    last = None
    since = 0
    for _ in range(max_iters):
        if await is_disconnected():
            break
        frame = progress_frame(store, plan_id)
        if frame != last:
            yield f"data: {json.dumps(frame)}\n\n"
            last = frame
            since = 0
        else:
            since += 1
            if since >= keepalive_every:
                yield ": keepalive\n\n"
                since = 0
        if is_terminal(frame["status"]):
            break
        await sleep(_STREAM_POLL_S)


def create_app(store: Optional[PlanStore] = None, auth: Optional[TokenAuth] = None,
               runner=None, run_sync: bool = False, deploy_runner=None,
               frontend_dist: Optional[str] = None, container_teardown=None) -> FastAPI:
    store = store or PlanStore()
    auth = auth or TokenAuth.from_env()
    job_runner = JobRunner(store, runner=runner, deploy_runner=deploy_runner,
                           container_teardown=container_teardown)

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

        # week-vs-weather guardrail (strict only when the configured EPW is readable)
        try:
            from webapp.jobs import pickle_load
            from planner.epw import week_within_epw, weather_coverage
            _wf = pickle_load(p.get("forecaster", "models/forecaster.pkl")).get("weather_file")
        except Exception:
            _wf = None
        if _wf:
            _week = _date.fromisoformat(p["week_start"])
            _days = _v("days", 7)
            if not week_within_epw(_wf, _week, _days):
                _cov = weather_coverage(_wf)
                raise HTTPException(422, f"week {_week} (+{_days}d) is outside the weather data "
                                         f"coverage ({_cov['label']}); pick a week within that window.")

        plan_id = f"gds-{params.week_start}-{uuid.uuid4().hex[:6]}"
        store.create_plan(plan_id, params.week_start, p)
        if run_sync:
            job_runner.runner(plan_id, p, store, lambda pr: store.write_progress(plan_id, pr))
        else:
            job_runner.submit(plan_id, p)
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
                "recommendation": store.get_recommendation(plan_id),
                "realized": store.get_realized(plan_id)}

    @app.get("/api/plans/{plan_id}/progress")
    def get_progress(plan_id: str, role: str = Depends(operator)):
        return store.read_progress(plan_id)

    @app.get("/api/plans/{plan_id}/stream")
    async def stream_plan(plan_id: str, request: Request, token: str = ""):
        # EventSource can't send headers, so the bearer rides in ?token=; reuse the existing check.
        auth.check(f"Bearer {token}", "operator")
        if store.get_plan_row(plan_id) is None:
            raise HTTPException(404, "plan not found")
        return StreamingResponse(
            plan_sse_stream(store, plan_id, request.is_disconnected),
            media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/plans/{plan_id}/trajectory")
    def get_trajectory(plan_id: str, role: str = Depends(operator)):
        if store.get_plan_row(plan_id) is None:
            raise HTTPException(404, "plan not found")
        return store.get_trajectory(plan_id)

    @app.post("/api/plans/{plan_id}/approve")
    def approve(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        row = store.get_plan_row(plan_id)
        if rec is None or row is None:
            raise HTTPException(404, "no recommendation yet")
        if not can_transition(row["status"], PlanStatus.APPROVED):
            raise HTTPException(409, f"cannot approve from {row['status']!r}")
        if rec.get("needs_revalidation"):
            raise HTTPException(409, "setpoints edited — re-validate before approving")
        rec["status"] = PlanStatus.APPROVED
        store.save_recommendation(plan_id, rec)
        return {"status": PlanStatus.APPROVED}

    @app.post("/api/plans/{plan_id}/reject")
    def reject(plan_id: str, role: str = Depends(expert)):
        rec = store.get_recommendation(plan_id)
        row = store.get_plan_row(plan_id)
        if rec is None or row is None:
            raise HTTPException(404, "no recommendation yet")
        if not can_transition(row["status"], PlanStatus.REJECTED):
            raise HTTPException(409, f"cannot reject from {row['status']!r}")
        rec["status"] = PlanStatus.REJECTED
        store.save_recommendation(plan_id, rec)
        return {"status": PlanStatus.REJECTED}

    @app.post("/api/plans/{plan_id}/cancel", status_code=202)
    def cancel_plan(plan_id: str, role: str = Depends(operator)):
        row = store.get_plan_row(plan_id)
        if row is None:
            raise HTTPException(404, "plan not found")
        if row["status"] not in ("queued", "running"):
            raise HTTPException(409, f"cannot cancel a {row['status']!r} plan")
        job_runner.request_cancel(plan_id)
        return {"status": "cancelling"}

    @app.delete("/api/plans/{plan_id}")
    def delete_plan_route(plan_id: str, role: str = Depends(operator)):
        row = store.get_plan_row(plan_id)
        if row is None:
            raise HTTPException(404, "plan not found")
        if row["status"] in ("queued", "running", "deploying"):
            raise HTTPException(409, f"cannot delete a {row['status']!r} plan; cancel it first")
        store.delete_plan(plan_id)
        return {"status": "deleted"}

    @app.post("/api/plans/{plan_id}/deploy", status_code=202)
    def deploy_plan(plan_id: str, role: str = Depends(expert)):
        row = store.get_plan_row(plan_id)
        if row is None or store.get_recommendation(plan_id) is None:
            raise HTTPException(404, "no recommendation yet")
        if not can_transition(row["status"], PlanStatus.DEPLOYING):
            raise HTTPException(409, f"cannot deploy from {row['status']!r}")
        if run_sync:
            job_runner.run_deploy_sync(plan_id)
        else:
            job_runner.submit_deploy(plan_id)
        return {"status": PlanStatus.DEPLOYING}

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

    from webapp.topology import build_hall_topology

    @app.get("/api/topology")
    def get_topology(hall: str = "1f 2a", role: str = Depends(operator)):
        return build_hall_topology("models/building.json", "configs/dt/dt.prototxt", hall)

    from planner.calibrator import load_calibration

    @app.get("/api/calibration")
    def get_calibration(role: str = Depends(operator)):
        return load_calibration("data/calibration.json").to_dict()

    @app.get("/api/weather")
    def get_weather(role: str = Depends(operator)):
        try:
            from webapp.jobs import pickle_load
            from planner.epw import weather_coverage, epw_first_date
            wf = pickle_load("models/forecaster.pkl").get("weather_file")
            cov = weather_coverage(wf)
            return {**cov, "file": wf, "suggested_week_start": epw_first_date(wf).isoformat()}
        except Exception:
            return {"label": None, "start_md": None, "end_md": None,
                    "file": None, "suggested_week_start": None}

    # Serve the built frontend at "/" (single origin — no separate dev server needed).
    # Mounted LAST so every /api/* route and /docs take precedence. If the UI isn't
    # built, "/" returns a friendly hint instead of FastAPI's bare 404.
    dist = (Path(frontend_dist) if frontend_dist is not None
            else Path(__file__).resolve().parent.parent / "frontend" / "dist")
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _frontend_not_built():
            return HTMLResponse(
                "<!doctype html><html><body "
                "style='font-family:system-ui;max-width:42rem;margin:3rem auto;line-height:1.5'>"
                "<h1>Digital Twin — API is running</h1>"
                "<p>The web UI hasn't been built, so there's nothing to serve at <code>/</code>.</p>"
                "<p><b>Build it once</b> — <code>npm --prefix src/frontend run build</code> — then "
                "reload (the backend serves it here at <code>/</code>).<br>"
                "Or for live development run the Vite dev server: "
                "<code>npm --prefix src/frontend run dev</code> &rarr; "
                "<a href='http://localhost:5173'>http://localhost:5173</a>.</p>"
                "<p>API docs: <a href='/docs'>/docs</a></p></body></html>")

    return app


app = create_app() if __name__ != "__main__" else None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # nosec
