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

    from webapp.topology import build_hall_topology

    @app.get("/api/topology")
    def get_topology(hall: str = "1f 2a", role: str = Depends(operator)):
        return build_hall_topology("models/building.json", "configs/dt/dt.prototxt", hall)

    return app


app = create_app() if __name__ != "__main__" else None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # nosec
