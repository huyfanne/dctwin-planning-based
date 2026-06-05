# Digital Twin Dual-Loop — Plan 1: Planner Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the heuristic best-first/coarse-to-fine planner that optimizes 3 global weekly setpoints, fully test-driven against a mock evaluator — with zero EnergyPlus or dctwin/dcbrain dependency.

**Architecture:** Pure-Python package `planner/` exposing an `Evaluator` protocol. The planner proposes candidate `Setpoints`, a `BroadcastPolicy` would later expand them to the env's 45-dim action vector, an `objective.score` ranks each candidate's `WeeklyKPI` (hard-reject infeasible + soft penalty), and `BeamPlanner` runs best-first coarse-to-fine search over the 3-D cube. A `MockEvaluator` with a known analytic cost surface stands in for EnergyPlus so the entire planner is TDD'd without simulation cost. Plan 2 swaps the real `ParallelEnvOracle` behind the same `Evaluator` protocol.

**Tech Stack:** Python 3.10+, numpy, pytest. No EnergyPlus, no Docker, no dctwin/dcbrain imports in this plan.

**Reference spec:** `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` (§3 decisions, §4.2 control bounds, §7.1–7.4 components).

**Note on commits:** This plan runs on branch `feat/dtwin-dual-loop-framework`. Append `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` to each commit message body (omitted from the short commands below for readability).

---

## File Structure

All paths are relative to the project root `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`.

| File | Responsibility |
|---|---|
| `pyproject.toml` | pytest config (`pythonpath`, `testpaths`) so `planner` imports cleanly |
| `planner/__init__.py` | package marker |
| `planner/types.py` | `Setpoints`, `Bounds`, `SearchSpace`, `WeeklyKPI`, `Evaluator` protocol, `DEFAULT_SEARCH_SPACE` |
| `planner/broadcast.py` | `ControlKind`, `ActionEntry`, `normalize`, `BroadcastPolicy` (3→N), `gds_action_spec` |
| `planner/objective.py` | `ObjectiveWeights`, `is_feasible`, `score` (hard reject + soft cost) |
| `planner/mock_evaluator.py` | `MockSurface`, `MockEvaluator` (analytic Evaluator for tests) |
| `planner/beam_search.py` | `BeamConfig`, `PlanResult`, `BeamPlanner` (best-first coarse-to-fine) |
| `tests/__init__.py` | test package marker |
| `tests/test_types.py` | bounds clipping, setpoints tuple |
| `tests/test_broadcast.py` | normalization round-trip, 3→45 order, masking-agnostic |
| `tests/test_objective.py` | hard reject, soft cost monotonic in energy |
| `tests/test_mock_evaluator.py` | deterministic analytic surface behavior |
| `tests/test_beam_search.py` | convergence, safety filter, budget cap, determinism, batch calls |

Each `planner/*.py` has one responsibility and is small enough to hold in context. `types.py` is the shared vocabulary every other module imports.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `planner/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create the environment**

Ensure numpy + pytest are available. Run from the project root:

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
python -m venv .venv && . .venv/bin/activate && pip install numpy pytest
```

(Or run inside the existing dctwin poetry environment, which already has numpy: `cd /mnt/lv/home/hoanghuy/newcode/dctwin && poetry run pip install pytest`, then run all commands below under `poetry run`.)

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Create package markers and a smoke test**

`planner/__init__.py`:

```python
"""Heuristic planner for the Digital Twin Dual-Loop Control Framework."""
```

`tests/__init__.py`:

```python
```

`tests/test_smoke.py`:

```python
def test_smoke():
    assert True
```

- [ ] **Step 4: Run the smoke test**

Run (from `src/`):

```bash
python -m pytest tests/test_smoke.py -v
```

Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pyproject.toml src/planner/__init__.py src/tests/__init__.py src/tests/test_smoke.py
git commit -m "chore(dtwin): scaffold planner-core package and pytest config"
```

---

## Task 2: Core types (`types.py`)

**Files:**
- Create: `planner/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_types.py`:

```python
import math
from planner.types import Setpoints, Bounds, SearchSpace, WeeklyKPI, DEFAULT_SEARCH_SPACE


def test_bounds_clip_inside_and_outside():
    b = Bounds(20.0, 26.0)
    assert b.clip(23.0) == 23.0
    assert b.clip(10.0) == 20.0
    assert b.clip(99.0) == 26.0


def test_setpoints_as_tuple_order():
    s = Setpoints(sat_c=24.0, flow_kg_s=8.0, chwst_c=17.0)
    assert s.as_tuple() == (24.0, 8.0, 17.0)


def test_search_space_clip_clamps_all_dims():
    s = Setpoints(sat_c=99.0, flow_kg_s=0.0, chwst_c=99.0)
    clipped = DEFAULT_SEARCH_SPACE.clip(s)
    assert clipped == Setpoints(26.0, 4.8, 19.0)


def test_default_search_space_matches_gds_bounds():
    assert DEFAULT_SEARCH_SPACE.sat == Bounds(20.0, 26.0)
    assert DEFAULT_SEARCH_SPACE.flow == Bounds(4.8, 13.8)
    assert DEFAULT_SEARCH_SPACE.chwst == Bounds(13.0, 19.0)


def test_weekly_kpi_defaults():
    k = WeeklyKPI(
        total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
    )
    assert k.inlet_excess_degc_steps == 0.0
    assert k.zone_temp_band_steps == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.types'`.

- [ ] **Step 3: Write the implementation**

`planner/types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence


@dataclass(frozen=True)
class Setpoints:
    """The 3 global weekly setpoints, in physical units."""

    sat_c: float          # CRAH supply-air temperature, deg C
    flow_kg_s: float      # CRAH supply-air mass flow per ACU, kg/s
    chwst_c: float        # chilled-water supply temperature, deg C

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.sat_c, self.flow_kg_s, self.chwst_c)


@dataclass(frozen=True)
class Bounds:
    """Inclusive physical bounds for one control dimension."""

    lb: float
    ub: float

    def clip(self, x: float) -> float:
        return max(self.lb, min(self.ub, x))


@dataclass(frozen=True)
class SearchSpace:
    sat: Bounds
    flow: Bounds
    chwst: Bounds

    def clip(self, s: Setpoints) -> Setpoints:
        return Setpoints(
            self.sat.clip(s.sat_c),
            self.flow.clip(s.flow_kg_s),
            self.chwst.clip(s.chwst_c),
        )


@dataclass
class WeeklyKPI:
    """Aggregated outcome of one full-week evaluation of a candidate."""

    total_hvac_energy_kwh: float
    pue_mean: float
    inlet_temp_max: float
    inlet_violation_steps: int
    rh_violation_steps: int
    feasible: bool
    # soft-penalty accumulators (filled by the evaluator; default 0)
    inlet_excess_degc_steps: float = 0.0
    rh_excursion_steps: float = 0.0
    zone_temp_band_steps: float = 0.0


class Evaluator(Protocol):
    """Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator."""

    def evaluate(
        self, candidates: Sequence[Setpoints], forecast: Optional[Any] = None
    ) -> list[WeeklyKPI]:
        ...


# GDS tropical-DC physical bounds (spec section 4.2)
DEFAULT_SEARCH_SPACE = SearchSpace(
    sat=Bounds(20.0, 26.0),
    flow=Bounds(4.8, 13.8),
    chwst=Bounds(13.0, 19.0),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_types.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/types.py src/tests/test_types.py
git commit -m "feat(dtwin): add planner core types (Setpoints, WeeklyKPI, Evaluator)"
```

---

## Task 3: Broadcast adapter (`broadcast.py`)

The 3 physical setpoints map to the env's N-dim normalized `[-1,1]` action vector. The adapter is parameterized by an ordered `ActionEntry` list so it is testable without the env. In Plan 2 the real ordered spec is derived from `dt.prototxt`'s `AGENT_CONTROLLED` declaration order.

**Files:**
- Create: `planner/broadcast.py`
- Test: `tests/test_broadcast.py`

- [ ] **Step 1: Write the failing test**

`tests/test_broadcast.py`:

```python
import numpy as np
import pytest

from planner.broadcast import (
    ControlKind,
    ActionEntry,
    normalize,
    BroadcastPolicy,
    gds_action_spec,
)
from planner.types import Setpoints


def test_normalize_endpoints_and_midpoint():
    assert normalize(20.0, 20.0, 26.0) == pytest.approx(-1.0)
    assert normalize(26.0, 20.0, 26.0) == pytest.approx(1.0)
    assert normalize(23.0, 20.0, 26.0) == pytest.approx(0.0)


def test_normalize_rejects_degenerate_bounds():
    with pytest.raises(ValueError):
        normalize(1.0, 5.0, 5.0)


def test_gds_action_spec_shape():
    spec = gds_action_spec()
    assert len(spec) == 45
    assert sum(1 for e in spec if e.kind is ControlKind.SAT) == 22
    assert sum(1 for e in spec if e.kind is ControlKind.FLOW) == 22
    assert sum(1 for e in spec if e.kind is ControlKind.CHWST) == 1


def test_broadcast_expands_in_declaration_order():
    spec = [
        ActionEntry(ControlKind.SAT, 20.0, 26.0),
        ActionEntry(ControlKind.FLOW, 4.8, 13.8),
        ActionEntry(ControlKind.CHWST, 13.0, 19.0),
    ]
    bp = BroadcastPolicy(spec)
    # midpoints -> all zeros
    out = bp.expand(Setpoints(sat_c=23.0, flow_kg_s=9.3, chwst_c=16.0))
    assert out.shape == (3,)
    np.testing.assert_allclose(out, [0.0, 0.0, 0.0], atol=1e-9)


def test_broadcast_full_gds_vector_endpoints():
    bp = BroadcastPolicy(gds_action_spec())
    out = bp.expand(Setpoints(sat_c=20.0, flow_kg_s=13.8, chwst_c=13.0))
    assert out.shape == (45,)
    # 22 SAT at lb -> -1, 22 FLOW at ub -> +1, 1 CHWST at lb -> -1
    np.testing.assert_allclose(out[:22], -1.0)
    np.testing.assert_allclose(out[22:44], 1.0)
    assert out[44] == pytest.approx(-1.0)


def test_broadcast_rejects_empty_spec():
    with pytest.raises(ValueError):
        BroadcastPolicy([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broadcast.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.broadcast'`.

- [ ] **Step 3: Write the implementation**

`planner/broadcast.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np

from planner.types import Setpoints


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


def normalize(x: float, lb: float, ub: float) -> float:
    """Physical value -> [-1, 1] linear normalization (matches dctwin LINEAR)."""
    if ub == lb:
        raise ValueError(f"degenerate bounds lb == ub == {lb}")
    return 2.0 * (x - lb) / (ub - lb) - 1.0


class BroadcastPolicy:
    """Expand the 3 global setpoints to the env's N-dim normalized action vector."""

    def __init__(self, action_spec: Sequence[ActionEntry]):
        if not action_spec:
            raise ValueError("action_spec must be non-empty")
        self.action_spec = list(action_spec)

    def expand(self, s: Setpoints) -> np.ndarray:
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

    ORDER WARNING: this assumes [22 SAT, 22 FLOW, 1 CHWST]. Plan 2 MUST verify
    this against the actual declaration order in
    configs/dt/dt.prototxt (the AGENT_CONTROLLED blocks) and reorder if needed.
    """
    spec: list[ActionEntry] = [ActionEntry(ControlKind.SAT, 20.0, 26.0) for _ in range(22)]
    spec += [ActionEntry(ControlKind.FLOW, 4.8, 13.8) for _ in range(22)]
    spec += [ActionEntry(ControlKind.CHWST, 13.0, 19.0)]
    return spec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_broadcast.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/broadcast.py src/tests/test_broadcast.py
git commit -m "feat(dtwin): add BroadcastPolicy (3 globals -> 45 normalized actions)"
```

---

## Task 4: Objective + safety filter (`objective.py`)

**Files:**
- Create: `planner/objective.py`
- Test: `tests/test_objective.py`

- [ ] **Step 1: Write the failing test**

`tests/test_objective.py`:

```python
import math

from planner.objective import ObjectiveWeights, is_feasible, score, INFEASIBLE
from planner.types import WeeklyKPI


def _kpi(energy=100.0, inlet_viol=0, rh_viol=0, inlet_excess=0.0,
         rh_exc=0.0, zone=0.0, feasible=True):
    return WeeklyKPI(
        total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=inlet_viol, rh_violation_steps=rh_viol,
        feasible=feasible, inlet_excess_degc_steps=inlet_excess,
        rh_excursion_steps=rh_exc, zone_temp_band_steps=zone,
    )


def test_feasible_when_no_violations():
    assert is_feasible(_kpi(), ObjectiveWeights())


def test_infeasible_when_inlet_violation_exceeds_tol():
    w = ObjectiveWeights(inlet_tol_steps=0)
    assert not is_feasible(_kpi(inlet_viol=1), w)
    assert score(_kpi(inlet_viol=1), w) == INFEASIBLE


def test_inlet_tolerance_allows_small_violations():
    w = ObjectiveWeights(inlet_tol_steps=3)
    assert is_feasible(_kpi(inlet_viol=3), w)
    assert not is_feasible(_kpi(inlet_viol=4), w)


def test_rh_hard_constraint_toggle():
    soft = ObjectiveWeights(rh_hard=False)
    hard = ObjectiveWeights(rh_hard=True, rh_tol_steps=0)
    assert is_feasible(_kpi(rh_viol=5), soft)
    assert not is_feasible(_kpi(rh_viol=5), hard)


def test_score_dominated_by_energy_and_monotonic():
    w = ObjectiveWeights()
    assert score(_kpi(energy=100.0), w) < score(_kpi(energy=200.0), w)


def test_score_adds_soft_penalties():
    w = ObjectiveWeights(lambda_temp=2.0, lambda_rh=0.5, lambda_zone=0.25)
    base = score(_kpi(energy=100.0), w)
    pen = score(_kpi(energy=100.0, inlet_excess=3.0, rh_exc=4.0, zone=8.0), w)
    assert pen == base + 2.0 * 3.0 + 0.5 * 4.0 + 0.25 * 8.0


def test_unfeasible_flag_forces_infeasible():
    assert score(_kpi(feasible=False), ObjectiveWeights()) == INFEASIBLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_objective.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.objective'`.

- [ ] **Step 3: Write the implementation**

`planner/objective.py`:

```python
from __future__ import annotations

import math
from dataclasses import dataclass

from planner.types import WeeklyKPI

INFEASIBLE = math.inf


@dataclass(frozen=True)
class ObjectiveWeights:
    """Soft-penalty weights and hard-constraint tolerances.

    Energy (kWh) is the dominant term; lambdas are small margin tie-breakers.
    """

    lambda_temp: float = 1.0      # weight on inlet margin excess (deg C * steps)
    lambda_rh: float = 0.2        # weight on humidity excursion
    lambda_zone: float = 0.1      # weight on zone-temp band excursion
    inlet_tol_steps: int = 0      # hard: allowed inlet-violation steps
    rh_hard: bool = False         # if True, rh violations are also a hard constraint
    rh_tol_steps: int = 0


def is_feasible(kpi: WeeklyKPI, w: ObjectiveWeights) -> bool:
    if not kpi.feasible:
        return False
    if kpi.inlet_violation_steps > w.inlet_tol_steps:
        return False
    if w.rh_hard and kpi.rh_violation_steps > w.rh_tol_steps:
        return False
    return True


def score(kpi: WeeklyKPI, w: ObjectiveWeights) -> float:
    """Lower is better. Infeasible candidates score +inf and never enter the beam."""
    if not is_feasible(kpi, w):
        return INFEASIBLE
    return (
        kpi.total_hvac_energy_kwh
        + w.lambda_temp * kpi.inlet_excess_degc_steps
        + w.lambda_rh * kpi.rh_excursion_steps
        + w.lambda_zone * kpi.zone_temp_band_steps
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_objective.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/objective.py src/tests/test_objective.py
git commit -m "feat(dtwin): add objective score with hard-reject + soft penalty"
```

---

## Task 5: Mock evaluator (`mock_evaluator.py`)

A deterministic analytic `Evaluator` so the search is TDD'd with no EnergyPlus. Energy is a convex bowl with a known minimum; inlet temperature rises with warmer SAT/CHWST and falls with higher flow, giving a known feasible/infeasible boundary.

**Files:**
- Create: `planner/mock_evaluator.py`
- Test: `tests/test_mock_evaluator.py`

- [ ] **Step 1: Write the failing test**

`tests/test_mock_evaluator.py`:

```python
from planner.mock_evaluator import MockSurface, MockEvaluator
from planner.types import Setpoints


def test_energy_minimized_at_optimum():
    ev = MockEvaluator(MockSurface(sat_opt=24.0, flow_opt=8.0, chwst_opt=17.0,
                                   energy_base=100.0, inlet_cap=999.0))
    at_opt = ev.evaluate([Setpoints(24.0, 8.0, 17.0)])[0]
    off_opt = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    assert at_opt.total_hvac_energy_kwh == 100.0
    assert off_opt.total_hvac_energy_kwh > at_opt.total_hvac_energy_kwh


def test_inlet_rises_with_sat_and_chwst_falls_with_flow():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    cool = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    hot = ev.evaluate([Setpoints(26.0, 4.8, 19.0)])[0]
    assert hot.inlet_temp_max > cool.inlet_temp_max


def test_violation_flagged_above_cap():
    ev = MockEvaluator(MockSurface(inlet_cap=22.0))
    hot = ev.evaluate([Setpoints(26.0, 4.8, 19.0)])[0]
    cool = ev.evaluate([Setpoints(20.0, 13.8, 13.0)])[0]
    assert hot.inlet_violation_steps > 0
    assert cool.inlet_violation_steps == 0


def test_deterministic_and_batched():
    ev = MockEvaluator()
    a = ev.evaluate([Setpoints(23.0, 9.0, 16.0), Setpoints(24.0, 8.0, 17.0)])
    b = ev.evaluate([Setpoints(23.0, 9.0, 16.0), Setpoints(24.0, 8.0, 17.0)])
    assert len(a) == 2
    assert a[0].total_hvac_energy_kwh == b[0].total_hvac_energy_kwh
    assert ev.call_count == 2
    assert len(ev.evaluated) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mock_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.mock_evaluator'`.

- [ ] **Step 3: Write the implementation**

`planner/mock_evaluator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from planner.types import Setpoints, WeeklyKPI


@dataclass
class MockSurface:
    """Analytic test surface: convex energy bowl + monotone inlet model."""

    sat_opt: float = 24.0
    flow_opt: float = 8.0
    chwst_opt: float = 17.0
    energy_base: float = 100.0
    inlet_base: float = 18.0
    k_sat: float = 1.0       # inlet sensitivity to SAT above 20 C
    k_chwst: float = 0.5     # inlet sensitivity to CHWST above 13 C
    k_flow: float = 0.4      # inlet reduction per kg/s of flow above 4.8
    inlet_cap: float = 26.0


class MockEvaluator:
    """Deterministic Evaluator for TDD of the planner (no EnergyPlus)."""

    def __init__(self, surface: Optional[MockSurface] = None):
        self.surface = surface or MockSurface()
        self.call_count = 0
        self.evaluated: list[Setpoints] = []

    def _kpi(self, s: Setpoints) -> WeeklyKPI:
        srf = self.surface
        energy = (
            srf.energy_base
            + (s.sat_c - srf.sat_opt) ** 2
            + (s.flow_kg_s - srf.flow_opt) ** 2
            + (s.chwst_c - srf.chwst_opt) ** 2
        )
        inlet = (
            srf.inlet_base
            + srf.k_sat * (s.sat_c - 20.0)
            + srf.k_chwst * (s.chwst_c - 13.0)
            - srf.k_flow * (s.flow_kg_s - 4.8)
        )
        violations = 0 if inlet <= srf.inlet_cap else 100
        excess = max(inlet - (srf.inlet_cap - 1.0), 0.0)
        return WeeklyKPI(
            total_hvac_energy_kwh=energy,
            pue_mean=1.2 + energy / 10000.0,
            inlet_temp_max=inlet,
            inlet_violation_steps=violations,
            rh_violation_steps=0,
            feasible=True,
            inlet_excess_degc_steps=excess,
        )

    def evaluate(
        self, candidates: Sequence[Setpoints], forecast: Optional[Any] = None
    ) -> list[WeeklyKPI]:
        self.call_count += 1
        self.evaluated.extend(candidates)
        return [self._kpi(s) for s in candidates]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mock_evaluator.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/mock_evaluator.py src/tests/test_mock_evaluator.py
git commit -m "test(dtwin): add deterministic MockEvaluator analytic surface"
```

---

## Task 6: Beam planner (`beam_search.py`)

Best-first, coarse-to-fine search over the 3-D cube. Level 0 is a `g`-per-dim grid; each later level samples a local neighborhood at half the previous step around each beam node. Every level scores its batch through the `Evaluator` (parallel-friendly) and keeps the top-`B`. Infeasible candidates (score `+inf`) sink to the bottom and are never returned as feasible.

**Files:**
- Create: `planner/beam_search.py`
- Test: `tests/test_beam_search.py`

- [ ] **Step 1: Write the failing test**

`tests/test_beam_search.py`:

```python
import pytest

from planner.beam_search import BeamConfig, BeamPlanner, PlanResult
from planner.objective import ObjectiveWeights, is_feasible
from planner.mock_evaluator import MockSurface, MockEvaluator
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


def test_converges_near_energy_optimum_when_unconstrained():
    # inlet_cap huge -> whole cube feasible; optimum at (24, 8, 17)
    ev = MockEvaluator(MockSurface(sat_opt=24.0, flow_opt=8.0, chwst_opt=17.0,
                                   energy_base=100.0, inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=5, beam_width=5, levels=3, neighbors=6))
    res = planner.plan()
    assert res.feasible
    # best energy must be very close to the bowl minimum (100.0)
    assert res.best_kpi.total_hvac_energy_kwh < 100.5
    assert res.evals <= res_evals_cap(planner)
    # best score per level is non-increasing
    assert all(b >= a for a, b in zip(res.history[1:], res.history[:-1]))


def res_evals_cap(planner):
    c = planner.config
    return c.grid ** 3 + c.levels * c.beam_width * c.neighbors


def test_never_returns_infeasible_candidate():
    # optimum (24,8,17) gives inlet 22.72 > cap 22 -> infeasible there
    ev = MockEvaluator(MockSurface(inlet_cap=22.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=5, beam_width=5, levels=3, neighbors=6))
    res = planner.plan()
    assert res.feasible
    assert res.best_kpi.inlet_temp_max <= 22.0 + 1e-9
    assert is_feasible(res.best_kpi, ObjectiveWeights())


def test_reports_infeasible_when_no_feasible_region():
    # cap below the coolest achievable inlet -> nothing feasible
    ev = MockEvaluator(MockSurface(inlet_cap=0.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=1, neighbors=6))
    res = planner.plan()
    assert res.feasible is False
    assert res.best is not None  # still returns a best-effort candidate


def test_respects_eval_budget():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=5,
                                     neighbors=6, max_evals=30))
    res = planner.plan()
    assert res.evals <= 30


def test_deterministic():
    surf = MockSurface(inlet_cap=999.0)
    cfg = BeamConfig(grid=4, beam_width=4, levels=2, neighbors=6)
    r1 = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(surf), ObjectiveWeights(), cfg).plan()
    r2 = BeamPlanner(DEFAULT_SEARCH_SPACE, MockEvaluator(surf), ObjectiveWeights(), cfg).plan()
    assert r1.best.as_tuple() == r2.best.as_tuple()
    assert r1.best_score == r2.best_score


def test_evaluates_in_batches_one_call_per_level():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=3, beam_width=3, levels=2, neighbors=6))
    planner.plan()
    # one batch for level 0 plus at most one per refine level
    assert 1 <= ev.call_count <= 3


def test_grid_must_be_at_least_two():
    ev = MockEvaluator()
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=1))
    with pytest.raises(ValueError):
        planner.plan()


def test_returned_candidate_within_bounds():
    ev = MockEvaluator(MockSurface(inlet_cap=999.0))
    planner = BeamPlanner(DEFAULT_SEARCH_SPACE, ev, ObjectiveWeights(),
                          BeamConfig(grid=4, beam_width=3, levels=2, neighbors=8))
    res = planner.plan()
    s = res.best
    assert 20.0 <= s.sat_c <= 26.0
    assert 4.8 <= s.flow_kg_s <= 13.8
    assert 13.0 <= s.chwst_c <= 19.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_beam_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.beam_search'`.

- [ ] **Step 3: Write the implementation**

`planner/beam_search.py`:

```python
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import numpy as np

from planner.objective import INFEASIBLE, ObjectiveWeights, score
from planner.types import Evaluator, SearchSpace, Setpoints, WeeklyKPI


@dataclass(frozen=True)
class BeamConfig:
    grid: int = 5            # g: coarse grid points per dim
    beam_width: int = 5      # B: frontier size kept each level
    levels: int = 3          # L: refine levels after the coarse grid
    neighbors: int = 6       # local samples per beam node per refine level
    max_evals: int = 400     # hard cap on total evaluations
    epsilon: float = 1e-3    # early-stop best-score improvement threshold


@dataclass
class PlanResult:
    best: Setpoints
    best_kpi: WeeklyKPI
    best_score: float
    evals: int
    feasible: bool
    history: list[float]     # best score after each level


# a scored candidate: (setpoints, kpi, score)
_Scored = tuple[Setpoints, WeeklyKPI, float]


def _coarse_grid(space: SearchSpace, g: int) -> list[Setpoints]:
    sats = np.linspace(space.sat.lb, space.sat.ub, g)
    flows = np.linspace(space.flow.lb, space.flow.ub, g)
    chwsts = np.linspace(space.chwst.lb, space.chwst.ub, g)
    return [
        Setpoints(float(a), float(b), float(c))
        for a, b, c in itertools.product(sats, flows, chwsts)
    ]


class BeamPlanner:
    def __init__(
        self,
        space: SearchSpace,
        evaluator: Evaluator,
        weights: Optional[ObjectiveWeights] = None,
        config: Optional[BeamConfig] = None,
    ):
        self.space = space
        self.evaluator = evaluator
        self.weights = weights or ObjectiveWeights()
        self.config = config or BeamConfig()

    def plan(self, forecast: Optional[Any] = None) -> PlanResult:
        cfg = self.config
        if cfg.grid < 2:
            raise ValueError("BeamConfig.grid must be >= 2")

        evals = 0
        history: list[float] = []

        # ---- Level 0: coarse grid (also capped by max_evals) ----
        candidates = _coarse_grid(self.space, cfg.grid)[: cfg.max_evals]
        scored = self._score_batch(candidates, forecast)
        evals += len(candidates)
        beam = self._top_b(scored, cfg.beam_width)
        history.append(beam[0][2])

        # half the coarse spacing per dim, halved again each refine level
        step = np.array(
            [
                (self.space.sat.ub - self.space.sat.lb) / (cfg.grid - 1),
                (self.space.flow.ub - self.space.flow.lb) / (cfg.grid - 1),
                (self.space.chwst.ub - self.space.chwst.lb) / (cfg.grid - 1),
            ]
        ) / 2.0

        # ---- Refine levels ----
        for _ in range(cfg.levels):
            if evals >= cfg.max_evals:
                break
            neigh: list[Setpoints] = []
            for s, _kpi, _sc in beam:
                neigh.extend(self._neighborhood(s, step, cfg.neighbors))
            neigh = neigh[: cfg.max_evals - evals]
            if not neigh:
                break
            scored_n = self._score_batch(neigh, forecast)
            evals += len(neigh)

            prev_best = beam[0][2]
            beam = self._top_b(beam + scored_n, cfg.beam_width)
            new_best = beam[0][2]
            history.append(new_best)
            step = step / 2.0

            if prev_best != INFEASIBLE and abs(prev_best - new_best) < cfg.epsilon:
                break

        best_s, best_kpi, best_sc = beam[0]
        feasible = best_sc != INFEASIBLE
        return PlanResult(best_s, best_kpi, best_sc, evals, feasible, history)

    def _score_batch(self, candidates: Sequence[Setpoints], forecast) -> list[_Scored]:
        kpis = self.evaluator.evaluate(candidates, forecast)
        return [(c, k, score(k, self.weights)) for c, k in zip(candidates, kpis)]

    @staticmethod
    def _top_b(scored: list[_Scored], b: int) -> list[_Scored]:
        # stable sort by score; +inf (infeasible) sinks to the bottom
        return sorted(scored, key=lambda t: t[2])[:b]

    def _neighborhood(self, s: Setpoints, step: np.ndarray, n: int) -> list[Setpoints]:
        base = np.array(s.as_tuple())
        offsets = [
            np.array([step[0], 0.0, 0.0]),
            np.array([-step[0], 0.0, 0.0]),
            np.array([0.0, step[1], 0.0]),
            np.array([0.0, -step[1], 0.0]),
            np.array([0.0, 0.0, step[2]]),
            np.array([0.0, 0.0, -step[2]]),
            np.array([step[0], step[1], 0.0]),
            np.array([-step[0], -step[1], 0.0]),
        ][:n]
        out: list[Setpoints] = []
        for off in offsets:
            p = base + off
            out.append(self.space.clip(Setpoints(float(p[0]), float(p[1]), float(p[2]))))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_beam_search.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Run the full suite + commit**

Run: `python -m pytest -v`
Expected: PASS (all tests across the 6 test files).

```bash
git add src/planner/beam_search.py src/tests/test_beam_search.py
git commit -m "feat(dtwin): add BeamPlanner best-first coarse-to-fine search"
```

---

## Task 7: Public API surface (`planner/__init__.py`)

Expose the package's public names so Plan 2/3 (and notebooks) import from one place.

**Files:**
- Modify: `planner/__init__.py`
- Test: `tests/test_public_api.py`

- [ ] **Step 1: Write the failing test**

`tests/test_public_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_public_api.py -v`
Expected: FAIL with `AssertionError: planner.Setpoints missing`.

- [ ] **Step 3: Write the implementation**

`planner/__init__.py`:

```python
"""Heuristic planner for the Digital Twin Dual-Loop Control Framework."""

from planner.types import (
    Setpoints,
    Bounds,
    SearchSpace,
    WeeklyKPI,
    Evaluator,
    DEFAULT_SEARCH_SPACE,
)
from planner.broadcast import (
    ControlKind,
    ActionEntry,
    normalize,
    BroadcastPolicy,
    gds_action_spec,
)
from planner.objective import ObjectiveWeights, is_feasible, score, INFEASIBLE
from planner.mock_evaluator import MockSurface, MockEvaluator
from planner.beam_search import BeamConfig, PlanResult, BeamPlanner

__all__ = [
    "Setpoints", "Bounds", "SearchSpace", "WeeklyKPI", "Evaluator",
    "DEFAULT_SEARCH_SPACE", "ControlKind", "ActionEntry", "normalize",
    "BroadcastPolicy", "gds_action_spec", "ObjectiveWeights", "is_feasible",
    "score", "INFEASIBLE", "MockSurface", "MockEvaluator", "BeamConfig",
    "PlanResult", "BeamPlanner",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_public_api.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run full suite + commit**

Run: `python -m pytest -v`
Expected: PASS (all tests).

```bash
git add src/planner/__init__.py src/tests/test_public_api.py
git commit -m "feat(dtwin): expose planner public API"
```

---

## Self-Review

**Spec coverage (Plan 1 scope = spec §7.1, §7.3, §7.4 + the MockEvaluator from §12):**
- §4.2 control bounds (SAT 20–26, flow 4.8–13.8, CHWST 13–19) → `DEFAULT_SEARCH_SPACE` (Task 2), `gds_action_spec` (Task 3). ✅
- §7.1 BroadcastPolicy 3→45 with LINEAR normalize → Task 3. ✅
- §7.4 objective: hard reject + soft cost, energy-dominant → Task 4. ✅
- §7.3 BeamPlanner best-first coarse-to-fine, beam/levels/budget/early-stop → Task 6. ✅
- §11 error handling: infeasible-region fallback (`feasible=False`, still returns best-effort) → Task 6 `test_reports_infeasible_when_no_feasible_region`. ✅
- §12 MockEvaluator drop-in `Evaluator` enabling EnglyPlus-free TDD → Task 5. ✅
- **Deferred to Plan 2** (correctly out of scope here): the real `ParallelEnvOracle`, `forecast` content, the exact 45-actuator declaration order (flagged in `gds_action_spec` docstring), per-candidate Docker error handling, timeouts.

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to" — every step has complete code and an exact command with expected output. ✅

**Type consistency:** `Setpoints(sat_c, flow_kg_s, chwst_c)`, `WeeklyKPI(...)` field names, `Evaluator.evaluate(candidates, forecast=None) -> list[WeeklyKPI]`, `score(kpi, weights)`, `BeamPlanner(space, evaluator, weights, config).plan(forecast=None) -> PlanResult` are used identically across Tasks 2–7. `ControlKind`/`ActionEntry` consistent between Task 3 def and `gds_action_spec`. ✅

---

## Execution Handoff

Plan 1 complete. It produces a fully-tested planner core (7 tasks, ~31 unit tests) with no EnergyPlus dependency. Plans 2 and 3 follow once this is green.
