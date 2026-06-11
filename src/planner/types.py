from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, Sequence


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

    def __post_init__(self) -> None:
        if self.lb > self.ub:
            raise ValueError(f"Bounds: lb ({self.lb}) > ub ({self.ub})")

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
    # Tariff/carbon-weighted energy: sum(step_kwh * rate[hour]) when the oracle
    # was given a tariff, else None (objective then uses raw energy). Appended
    # LAST with a default so positional construction sites keep working.
    weighted_energy_cost: Optional[float] = None


class Evaluator(Protocol):
    """Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator."""

    def evaluate(
        self, candidates: Sequence[Setpoints], forecast: Optional[Any] = None,
        on_result: Optional[Callable[[], None]] = None,
    ) -> list[WeeklyKPI]:
        """`on_result`, if given, is called once per candidate as it finishes
        (for live progress); evaluation order is not guaranteed under a pool."""
        ...


# GDS tropical-DC physical bounds (spec section 4.2)
DEFAULT_SEARCH_SPACE = SearchSpace(
    sat=Bounds(20.0, 26.0),
    flow=Bounds(4.8, 13.8),
    chwst=Bounds(13.0, 19.0),
)
