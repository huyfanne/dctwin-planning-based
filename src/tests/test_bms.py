import json

import pytest

from planner.bms import BacnetBmsAdapter, ShadowBmsAdapter
from planner.types import Setpoints

SP = Setpoints(sat_c=24.0, flow_kg_s=6.2, chwst_c=18.0)


def test_shadow_apply_writes_45_denormalized_commands(tmp_path):
    out = ShadowBmsAdapter().apply(SP, "2013-11-11", tmp_path)
    artifact = json.loads((tmp_path / "bms_commands.json").read_text())

    assert artifact["mode"] == "shadow"
    assert artifact["actuated"] is False
    assert artifact["week_start"] == "2013-11-11"
    assert artifact["written_at"]
    cmds = artifact["commands"]
    assert len(cmds) == 45

    sat = [c for c in cmds if c["point"].endswith("_supply_air_temperature_setpoint")
           and c["point"].startswith("data_hall_1f_2a_acu_")]
    flow = [c for c in cmds if c["point"].endswith("_supply_air_mass_flow_rate")]
    chwst = [c for c in cmds if c["point"] == "chilled_water_loop_supply_temperature_setpoint"]
    assert len(sat) == 22 and len(flow) == 22 and len(chwst) == 1
    # physical (denormalized) values, not [-1, 1] broadcast actions
    assert all(c["value"] == 24.0 and c["unit"] == "C" for c in sat)
    assert all(c["value"] == 6.2 and c["unit"] == "kg/s" for c in flow)
    assert chwst[0]["value"] == 18.0 and chwst[0]["unit"] == "C"

    assert out == {"mode": "shadow", "n_commands": 45,
                   "artifact": str(tmp_path / "bms_commands.json")}


def test_shadow_apply_order_matches_gds_action_spec(tmp_path):
    # declaration order in dt.prototxt: 22 SAT, 22 FLOW (acu_1..acu_22 each), then CHWST
    ShadowBmsAdapter().apply(SP, "2013-11-11", tmp_path)
    points = [c["point"] for c in
              json.loads((tmp_path / "bms_commands.json").read_text())["commands"]]
    assert points[:22] == [f"data_hall_1f_2a_acu_{i}_supply_air_temperature_setpoint"
                           for i in range(1, 23)]
    assert points[22:44] == [f"data_hall_1f_2a_acu_{i}_supply_air_mass_flow_rate"
                             for i in range(1, 23)]
    assert points[44] == "chilled_water_loop_supply_temperature_setpoint"


def test_shadow_apply_accepts_date_and_creates_out_dir(tmp_path):
    from datetime import date
    out_dir = tmp_path / "deploy"           # does not exist yet
    ShadowBmsAdapter().apply(SP, date(2013, 11, 11), out_dir)
    artifact = json.loads((out_dir / "bms_commands.json").read_text())
    assert artifact["week_start"] == "2013-11-11"


def test_bacnet_adapter_is_an_explicit_field_seam():
    with pytest.raises(NotImplementedError):
        BacnetBmsAdapter().apply(SP, "2013-11-11", "/tmp/x")
