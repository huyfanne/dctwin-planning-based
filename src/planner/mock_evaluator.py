from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from planner.types import Setpoints, WeeklyKPI


@dataclass(frozen=True)
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
        # accumulate inlet excess starting 1 deg C BELOW the hard cap (soft-margin signal)
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
        self, candidates: Sequence[Setpoints], forecast: Optional[Any] = None,
        on_result: Optional[Callable[[], None]] = None,
    ) -> list[WeeklyKPI]:
        self.call_count += 1
        self.evaluated.extend(candidates)
        out = []
        for s in candidates:
            out.append(self._kpi(s))
            if on_result is not None:
                on_result()
        return out

    def replay_with_trajectory(self, setpoints, forecast=None, n_steps: int = 8):
        from planner.kpi import StepSample
        kpi = self.evaluate([setpoints], forecast)[0]
        samples = [
            StepSample(total_power_w=1200.0, it_power_w=1000.0,
                       inlet_temps=[kpi.inlet_temp_max])
            for _ in range(n_steps)
        ]
        return kpi, samples
