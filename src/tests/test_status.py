from webapp.status import PlanStatus, can_transition


def test_allowed_transitions():
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.APPROVED, PlanStatus.DEPLOYING)
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOYED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_FAILED)


def test_unsafe_statuses_are_not_approvable():
    # the safety property: a plan that is not robust-feasible cannot be approved
    assert not can_transition(PlanStatus.BLOCKED_UNSAFE, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.BLOCKED_UNSAFE, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.REJECTED)


def test_deploy_blocked_allows_retry_or_reject():
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_BLOCKED)
    assert can_transition(PlanStatus.DEPLOY_BLOCKED, PlanStatus.DEPLOYING)
    assert can_transition(PlanStatus.DEPLOY_BLOCKED, PlanStatus.REJECTED)


def test_forbidden_transitions():
    assert not can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.DEPLOYED)
    assert not can_transition(PlanStatus.REJECTED, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.DEPLOYED, PlanStatus.APPROVED)
