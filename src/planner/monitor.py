from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonitorSpec:
    total_power_name: str
    it_power_name: str
    inlet_temp_names: list[str] = field(default_factory=list)
    inlet_rh_names: list[str] = field(default_factory=list)
    zone_temp_names: list[str] = field(default_factory=list)


def discover_monitor(env, hall: str = "") -> MonitorSpec:
    """Scan a dctwin env's observations and classify the ones we read each step.

    Power (total / IT) is facility-wide. The thermal sensors (inlet temp/RH, zone
    temp) are scoped to `hall` (a case-insensitive substring, e.g. "1f 2a") when
    given, so the thermal KPI reflects only the controlled hall -- sensors in
    halls we do not actuate would otherwise pin the KPI to a constant value.
    """
    unwrapped = getattr(env, "unwrapped", env)
    names = [o.variable_name for o in unwrapped.observations]

    total = next((n for n in names if n == "total power"), None)
    it = next((n for n in names if n == "total it power"), None)
    if total is None or it is None:
        raise ValueError("env is missing 'total power' / 'total it power' observations")

    inlet_temps = [n for n in names if "inlet dry-bulb temperature" in n.lower()]
    inlet_rhs = [n for n in names if "inlet relative humidity" in n.lower()]
    # room/zone air temperature, but not ACU/coil inlet readings
    zones = [
        n for n in names
        if n.lower().endswith(" air temperature") and "acu" not in n.lower()
        and "inlet" not in n.lower()
    ]
    if hall:
        h = hall.lower()
        inlet_temps = [n for n in inlet_temps if h in n.lower()]
        inlet_rhs = [n for n in inlet_rhs if h in n.lower()]
        zones = [n for n in zones if h in n.lower()]
    return MonitorSpec(total, it, inlet_temps, inlet_rhs, zones)
