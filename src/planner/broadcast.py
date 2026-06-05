from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np

from planner.types import Setpoints, DEFAULT_SEARCH_SPACE


class ControlKind(Enum):
    SAT = "sat"
    FLOW = "flow"
    CHWST = "chwst"


@dataclass(frozen=True)
class ActionEntry:
    """One env actuator: which global control feeds it, and its physical bounds."""

    kind: ControlKind
    lb: float
    ub: float

    def __post_init__(self) -> None:
        if self.lb > self.ub:
            raise ValueError(f"ActionEntry bounds: lb ({self.lb}) > ub ({self.ub})")


def normalize(x: float, lb: float, ub: float) -> float:
    """Physical value -> [-1, 1] linear normalization (matches dctwin LINEAR)."""
    if ub <= lb:
        raise ValueError(f"normalize requires lb < ub, got lb={lb}, ub={ub}")
    return 2.0 * (x - lb) / (ub - lb) - 1.0


class BroadcastPolicy:
    """Expand the 3 global setpoints to the env's N-dim normalized action vector."""

    def __init__(self, action_spec: Sequence[ActionEntry]):
        if not action_spec:
            raise ValueError("action_spec must be non-empty")
        self.action_spec = list(action_spec)

    def expand(self, s: Setpoints) -> np.ndarray:
        """Expand to the N-dim normalized vector. Values outside [lb,ub] pass through (caller pre-clips via SearchSpace.clip)."""
        values = {
            ControlKind.SAT: s.sat_c,
            ControlKind.FLOW: s.flow_kg_s,
            ControlKind.CHWST: s.chwst_c,
        }
        out = np.empty(len(self.action_spec), dtype=float)
        for i, entry in enumerate(self.action_spec):
            out[i] = normalize(values[entry.kind], entry.lb, entry.ub)
        return out


def gds_action_spec() -> list[ActionEntry]:
    """The GDS model's 45 AGENT_CONTROLLED actuators.

    Bounds come from DEFAULT_SEARCH_SPACE (single source of truth).
    ORDER WARNING: this assumes [22 SAT, 22 FLOW, 1 CHWST]. Plan 2 MUST verify
    this against the actual declaration order in configs/dt/dt.prototxt.
    """
    s = DEFAULT_SEARCH_SPACE
    spec: list[ActionEntry] = [ActionEntry(ControlKind.SAT, s.sat.lb, s.sat.ub) for _ in range(22)]
    spec += [ActionEntry(ControlKind.FLOW, s.flow.lb, s.flow.ub) for _ in range(22)]
    spec += [ActionEntry(ControlKind.CHWST, s.chwst.lb, s.chwst.ub)]
    return spec
