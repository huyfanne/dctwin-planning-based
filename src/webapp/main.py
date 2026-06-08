from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException

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


def create_app(store: Optional[PlanStore] = None, auth: Optional[TokenAuth] = None,
               runner=None, run_sync: bool = False, deploy_runner=None) -> FastAPI:
    store = store or PlanStore()
    auth = auth or TokenAuth.from_env()
    job_runner = JobRunner(store, runner=runner, deploy_runner=deploy_runner)

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

    return app


app = create_app() if __name__ != "__main__" else None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # nosec
