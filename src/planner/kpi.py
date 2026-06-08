from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from planner.types import WeeklyKPI


@dataclass
class StepSample:
    """One timestep's monitored readings (physical units)."""

    total_power_w: float
    it_power_w: float
    inlet_temps: list[float]      # ITE inlet dry-bulb, deg C
    inlet_rhs: list[float] = field(default_factory=list)   # %
    zone_temps: list[float] = field(default_factory=list)  # deg C
    # Hall-scoped controllable HVAC power (ACU fans + chiller/CHW plant), summed
    # from MonitorSpec.hvac_power_names. None = not measured -> fall back to the
    # facility total_power_w - it_power_w (keeps the mock/legacy paths working).
    hvac_power_w: Optional[float] = None


def _hvac_watts(smp: "StepSample") -> float:
    """Controllable HVAC power for energy: the scoped hall+plant sum when measured,
    else facility (total - IT) as a back-compat fallback."""
    return smp.hvac_power_w if smp.hvac_power_w is not None else (smp.total_power_w - smp.it_power_w)


@dataclass(frozen=True)
class OracleSettings:
    inlet_cap: float = 26.0          # hard ITE inlet limit, deg C
    inlet_soft_margin: float = 1.0   # soft threshold = cap - margin
    rh_min: float = 30.0
    rh_max: float = 60.0
    zone_target: float = 32.0
    zone_band: float = 1.0
    # Discard the initial control-startup transient (the BCVTB loop spikes for a
    # few steps before setpoints propagate through the HVAC system) before scoring.
    # Guarded so tiny test runs (<= warmup_steps samples) are unaffected.
    warmup_steps: int = 6


def aggregate_kpi(samples: list[StepSample], hours_per_step: float,
                  settings: OracleSettings) -> WeeklyKPI:
    if not samples:
        return WeeklyKPI(
            total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
            inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
            rh_violation_steps=10 ** 9, feasible=False,
        )

    s = settings
    if len(samples) > s.warmup_steps:
        samples = samples[s.warmup_steps:]
    soft_threshold = s.inlet_cap - s.inlet_soft_margin

    energy_kwh = 0.0
    pue_sum = 0.0
    pue_count = 0
    inlet_temp_max = float("-inf")
    inlet_violation_steps = 0
    inlet_excess = 0.0
    rh_violation_steps = 0
    rh_excursion = 0.0
    zone_band_steps = 0.0

    for smp in samples:
        hvac_w = _hvac_watts(smp)
        energy_kwh += hvac_w * hours_per_step / 1000.0
        if smp.it_power_w > 0:
            pue_sum += smp.total_power_w / smp.it_power_w
            pue_count += 1

        step_inlet_max = max(smp.inlet_temps) if smp.inlet_temps else float("-inf")
        inlet_temp_max = max(inlet_temp_max, step_inlet_max)
        if step_inlet_max > s.inlet_cap:
            inlet_violation_steps += 1
        inlet_excess += max(step_inlet_max - soft_threshold, 0.0)

        rh_bad = False
        for rh in smp.inlet_rhs:
            if rh < s.rh_min:
                rh_bad = True
                rh_excursion += s.rh_min - rh
            elif rh > s.rh_max:
                rh_bad = True
                rh_excursion += rh - s.rh_max
        if rh_bad:
            rh_violation_steps += 1

        for z in smp.zone_temps:
            zone_band_steps += max(abs(z - s.zone_target) - s.zone_band, 0.0)

    return WeeklyKPI(
        total_hvac_energy_kwh=energy_kwh,
        pue_mean=pue_sum / pue_count if pue_count else float("inf"),
        inlet_temp_max=inlet_temp_max,
        inlet_violation_steps=inlet_violation_steps,
        rh_violation_steps=rh_violation_steps,
        feasible=True,
        inlet_excess_degc_steps=inlet_excess,
        rh_excursion_steps=rh_excursion,
        zone_temp_band_steps=zone_band_steps,
    )


def step_trajectory(samples: list[StepSample], hours_per_step: float,
                    settings: OracleSettings) -> list[dict]:
    """Per-step series for the pre-validation trajectory CSV. Applies the same
    warmup discard as aggregate_kpi so the plot matches the scored window."""
    s = settings
    if len(samples) > s.warmup_steps:
        samples = samples[s.warmup_steps:]
    rows = []
    for i, smp in enumerate(samples):
        hvac_w = _hvac_watts(smp)
        rows.append({
            "step": i,
            "inlet_temp_max_c": max(smp.inlet_temps) if smp.inlet_temps else None,
            "hvac_power_kw": hvac_w / 1000.0,
            "pue": (smp.total_power_w / smp.it_power_w) if smp.it_power_w > 0 else None,
        })
    return rows
