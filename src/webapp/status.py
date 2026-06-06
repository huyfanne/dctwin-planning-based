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
