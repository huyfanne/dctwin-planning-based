from webapp.status import PlanStatus, can_transition


def test_allowed_transitions():
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.APPROVED, PlanStatus.DEPLOYING)
    assert can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.REJECTED)
    assert can_transition(PlanStatus.INFEASIBLE_FALLBACK, PlanStatus.APPROVED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOYED)
    assert can_transition(PlanStatus.DEPLOYING, PlanStatus.DEPLOY_FAILED)


def test_forbidden_transitions():
    assert not can_transition(PlanStatus.PENDING_APPROVAL, PlanStatus.DEPLOYED)
    assert not can_transition(PlanStatus.REJECTED, PlanStatus.APPROVED)
    assert not can_transition(PlanStatus.DEPLOYED, PlanStatus.APPROVED)
