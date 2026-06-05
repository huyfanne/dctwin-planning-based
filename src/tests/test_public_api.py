def test_public_api_imports():
    import planner
    for name in [
        "Setpoints", "WeeklyKPI", "SearchSpace", "Bounds", "DEFAULT_SEARCH_SPACE",
        "BroadcastPolicy", "gds_action_spec", "ControlKind", "ActionEntry",
        "ObjectiveWeights", "score", "is_feasible",
        "BeamPlanner", "BeamConfig", "PlanResult",
        "MockEvaluator", "MockSurface",
    ]:
        assert hasattr(planner, name), f"planner.{name} missing"
