from __future__ import annotations

from typing import Sequence

from planner.broadcast import ActionEntry, BroadcastPolicy, ControlKind
from planner.types import DEFAULT_SEARCH_SPACE

AGENT_CONTROLLED = 2  # dctwin ControlType enum value (dt_engine.proto)


def classify_kind(variable_name: str) -> ControlKind:
    name = variable_name.lower()
    if "supply_air_temperature_setpoint" in name:
        return ControlKind.SAT
    if "supply_air_mass_flow_rate" in name:
        return ControlKind.FLOW
    if "chilled_water_loop_supply_temperature" in name:
        return ControlKind.CHWST
    raise ValueError(f"Unknown AGENT_CONTROLLED action: {variable_name!r}")


def bounds_for(kind: ControlKind) -> tuple[float, float]:
    """Per-kind physical bounds (match the GDS dt.prototxt normalize_config)."""
    b = {
        ControlKind.SAT: DEFAULT_SEARCH_SPACE.sat,
        ControlKind.FLOW: DEFAULT_SEARCH_SPACE.flow,
        ControlKind.CHWST: DEFAULT_SEARCH_SPACE.chwst,
    }[kind]
    return (b.lb, b.ub)


def action_spec_from_actions(actions: Sequence) -> list[ActionEntry]:
    """Build the ordered ActionEntry list from a live env's actions list.

    Keeps only control_type == AGENT_CONTROLLED, in declaration order.
    """
    spec: list[ActionEntry] = []
    for act in actions:
        if getattr(act, "control_type", None) != AGENT_CONTROLLED:
            continue
        kind = classify_kind(act.variable_name)
        lb, ub = bounds_for(kind)
        spec.append(ActionEntry(kind, lb, ub))
    if not spec:
        raise ValueError("No AGENT_CONTROLLED actions found in env")
    return spec


def mapper_from_env(env) -> BroadcastPolicy:
    """Derive a BroadcastPolicy from a (possibly gym-wrapped) dctwin env."""
    unwrapped = getattr(env, "unwrapped", env)
    return BroadcastPolicy(action_spec_from_actions(unwrapped.actions))
