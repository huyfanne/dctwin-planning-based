from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from planner.broadcast import ControlKind, gds_action_spec
from planner.types import Setpoints

# BMS point-name templates for the GDS AGENT_CONTROLLED actuators, matching the
# declaration order in configs/dt/dt.prototxt (the same [22 SAT, 22 FLOW, 1 CHWST]
# order gds_action_spec() encodes). Per-kind index is 1-based (acu_1..acu_22).
_POINT_TEMPLATES = {
    ControlKind.SAT: ("data_hall_1f_2a_acu_{i}_supply_air_temperature_setpoint", "C"),
    ControlKind.FLOW: ("data_hall_1f_2a_acu_{i}_supply_air_mass_flow_rate", "kg/s"),
    ControlKind.CHWST: ("chilled_water_loop_supply_temperature_setpoint", "C"),
}


def expand_commands(setpoints: Setpoints) -> list[dict]:
    """Expand the 3 global setpoints to the 45 per-actuator BMS commands.

    Values are PHYSICAL (denormalized) — a BMS speaks degC / kg/s, not the
    [-1, 1] action vector BroadcastPolicy emits for the env.
    """
    values = {
        ControlKind.SAT: setpoints.sat_c,
        ControlKind.FLOW: setpoints.flow_kg_s,
        ControlKind.CHWST: setpoints.chwst_c,
    }
    counters: dict[ControlKind, int] = {k: 0 for k in ControlKind}
    commands: list[dict] = []
    for entry in gds_action_spec():
        counters[entry.kind] += 1
        template, unit = _POINT_TEMPLATES[entry.kind]
        commands.append({
            "point": template.format(i=counters[entry.kind]),
            "value": values[entry.kind],
            "unit": unit,
        })
    return commands


class ShadowBmsAdapter:
    """Shadow-mode BMS seam: records what WOULD be commanded, never actuates.

    No physical BMS exists on this rig, so the adapter's only side effect is the
    bms_commands.json artifact — an auditable record the field adapter
    (BacnetBmsAdapter) will later replay against real hardware.
    """

    def apply(self, setpoints: Setpoints, week_start, out_dir) -> dict:
        """Write out_dir/bms_commands.json (45 commands, actuated:false).

        `week_start` may be a date or an ISO string; `out_dir` is created if
        missing (deploy() passes runs/<id>/deploy/).
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = out_dir / "bms_commands.json"
        artifact = {
            "mode": "shadow",
            "week_start": str(week_start),
            "written_at": datetime.now(timezone.utc).isoformat(),
            "commands": expand_commands(setpoints),
            "actuated": False,
        }
        artifact_path.write_text(json.dumps(artifact, indent=2))
        return {"mode": "shadow", "n_commands": len(artifact["commands"]),
                "artifact": str(artifact_path)}


class BacnetBmsAdapter:
    """Field-BMS seam (NOT implemented — no physical BMS on this rig).

    Implementing it requires site config that does not exist yet:
      - BACnet/IP host + port of the building controller,
      - a device map {point name -> (device_id, object_type, object_instance)}
        for all 45 GDS actuators (22 ACU SAT, 22 ACU flow, 1 CHWST),
      - write-priority and relinquish policy agreed with facility ops.
    Same contract as ShadowBmsAdapter.apply, but actuated:true.
    """

    def apply(self, setpoints: Setpoints, week_start, out_dir) -> dict:
        raise NotImplementedError(
            "BacnetBmsAdapter needs site config (BACnet host, 45-point device map, "
            "write priority); use ShadowBmsAdapter until a physical BMS exists"
        )
