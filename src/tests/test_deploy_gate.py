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
