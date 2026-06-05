from __future__ import annotations

from dataclasses import dataclass, field

from planner.types import WeeklyKPI


@dataclass
class StepSample:
    """One timestep's monitored readings (physical units)."""

    total_power_w: float
    it_power_w: float
    inlet_temps: list[float]      # ITE inlet dry-bulb, deg C
    inlet_rhs: list[float] = field(default_factory=list)   # %
    zone_temps: list[float] = field(default_factory=list)  # deg C


@dataclass(frozen=True)
class OracleSettings:
    inlet_cap: float = 26.0          # hard ITE inlet limit, deg C
    inlet_soft_margin: float = 1.0   # soft threshold = cap - margin
    rh_min: float = 30.0
    rh_max: float = 60.0
    zone_target: float = 32.0
    zone_band: float = 1.0


def aggregate_kpi(samples: list[StepSample], hours_per_step: float,
                  settings: OracleSettings) -> WeeklyKPI:
    if not samples:
        return WeeklyKPI(
            total_hvac_energy_kwh=float("inf"), pue_mean=float("inf"),
            inlet_temp_max=float("inf"), inlet_violation_steps=10 ** 9,
            rh_violation_steps=10 ** 9, feasible=False,
        )

    s = settings
    soft_threshold = s.inlet_cap - s.inlet_soft_margin

    energy_kwh = 0.0
    pue_sum = 0.0
    inlet_temp_max = float("-inf")
    inlet_violation_steps = 0
    inlet_excess = 0.0
    rh_violation_steps = 0
    rh_excursion = 0.0
    zone_band_steps = 0.0

    for smp in samples:
        hvac_w = smp.total_power_w - smp.it_power_w
        energy_kwh += hvac_w * hours_per_step / 1000.0
        if smp.it_power_w > 0:
            pue_sum += smp.total_power_w / smp.it_power_w

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
        pue_mean=pue_sum / len(samples),
        inlet_temp_max=inlet_temp_max,
        inlet_violation_steps=inlet_violation_steps,
        rh_violation_steps=rh_violation_steps,
        feasible=True,
        inlet_excess_degc_steps=inlet_excess,
        rh_excursion_steps=rh_excursion,
        zone_temp_band_steps=zone_band_steps,
    )
