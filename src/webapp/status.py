"""Plan status values + the allowed transition graph (the outer-loop state machine)."""
from __future__ import annotations


class PlanStatus:
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    PENDING_APPROVAL = "pending_approval"
    INFEASIBLE_FALLBACK = "infeasible_fallback"   # nominal search found nothing feasible
    BLOCKED_UNSAFE = "blocked_unsafe"             # robust re-rank: no finalist is safe
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    DEPLOY_FAILED = "deploy_failed"               # the deploy job crashed
    DEPLOY_BLOCKED = "deploy_blocked"             # approved plan breached on the real plant
    CANCELLED = "cancelled"                        # operator cancelled a running/queued plan


# expert/operator-driven transitions (the worker sets queued/running/failed/deploy_* itself)
_ALLOWED = {
    PlanStatus.PENDING_APPROVAL: {PlanStatus.APPROVED, PlanStatus.REJECTED},
    # unsafe plans are NOT approvable — only rejectable (the gate's single source of truth)
    PlanStatus.INFEASIBLE_FALLBACK: {PlanStatus.REJECTED},
    PlanStatus.BLOCKED_UNSAFE: {PlanStatus.REJECTED},
    PlanStatus.APPROVED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
    PlanStatus.DEPLOYING: {PlanStatus.DEPLOYED, PlanStatus.DEPLOY_FAILED,
                           PlanStatus.DEPLOY_BLOCKED},
    PlanStatus.DEPLOY_FAILED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
    PlanStatus.DEPLOY_BLOCKED: {PlanStatus.DEPLOYING, PlanStatus.REJECTED},
}


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())
