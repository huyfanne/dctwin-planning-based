import json
from datetime import date

import pytest

from deploy import deploy
from planner.types import Setpoints, WeeklyKPI


class _FakeOracle:
    def __init__(self):
        self.calls = 0
    def evaluate(self, candidates, forecast=None):
        self.calls += 1
        return [WeeklyKPI(total_hvac_energy_kwh=77.0, pue_mean=1.19, inlet_temp_max=25.0,
                          inlet_violation_steps=0, rh_violation_steps=0, feasible=True)]


def _rec(status):
    return {
        "schema_version": "1.0", "plan_id": "gds-x", "week_start": "2013-11-11",
        "week_end": "2013-11-17", "cadence": "weekly",
        "setpoints": {"crah_supply_air_temperature_c": 24.0,
                      "crah_supply_air_mass_flow_rate_kg_s": 6.2,
                      "chilled_water_supply_temperature_c": 18.0},
        "predicted_kpis": {}, "forecast": {}, "search": {}, "status": status,
    }


def test_deploy_refuses_when_not_approved(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("pending_approval")))
    with pytest.raises(PermissionError):
        deploy(str(p), oracle=_FakeOracle())


def test_deploy_runs_and_records_realized_when_approved(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("approved")))
    orc = _FakeOracle()
    deploy(str(p), oracle=orc)
    out = json.loads(p.read_text())
    assert orc.calls == 1
    assert out["status"] == "deployed"
    assert out["realized_kpis"]["total_hvac_energy_kwh"] == 77.0


def test_deploy_without_bms_keeps_sim_only_artifact_shape(tmp_path):
    # sim mode (bms=None) must be byte-for-byte today's behavior: no shadow fields,
    # no schema bump, no deploy/ artifact.
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("approved")))
    deploy(str(p), oracle=_FakeOracle())
    out = json.loads(p.read_text())
    assert out["schema_version"] == "1.0"
    for k in ("deploy_mode", "bms", "realized_source"):
        assert k not in out
    assert not (tmp_path / "deploy").exists()


def test_deploy_with_bms_stamps_rec_and_records_commands(tmp_path):
    from planner.bms import ShadowBmsAdapter

    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("approved")))
    rec = deploy(str(p), oracle=_FakeOracle(), bms=ShadowBmsAdapter())
    out = json.loads(p.read_text())
    assert out == rec

    # additive schema 1.8: deploy_mode + bms + realized_source
    assert out["schema_version"] == "1.8"
    assert out["deploy_mode"] == "shadow"
    assert out["realized_source"] == "sim"
    assert out["bms"]["mode"] == "shadow"
    assert out["bms"]["n_commands"] == 45
    # the realized week still comes from the oracle (observation stand-in)
    assert out["status"] == "deployed"
    assert out["realized_kpis"]["total_hvac_energy_kwh"] == 77.0

    # commands recorded under <plan_dir>/deploy/, never actuated
    artifact = json.loads((tmp_path / "deploy" / "bms_commands.json").read_text())
    assert out["bms"]["artifact"] == str(tmp_path / "deploy" / "bms_commands.json")
    assert artifact["actuated"] is False
    assert len(artifact["commands"]) == 45


def test_deploy_with_bms_still_requires_approval(tmp_path):
    from planner.bms import ShadowBmsAdapter

    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("pending_approval")))
    with pytest.raises(PermissionError):
        deploy(str(p), oracle=_FakeOracle(), bms=ShadowBmsAdapter())
    assert not (tmp_path / "deploy").exists()   # no commands recorded pre-approval
