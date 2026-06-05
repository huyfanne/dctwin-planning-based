import numpy as np
import pytest

from planner.env_actions import classify_kind, bounds_for, action_spec_from_actions, mapper_from_env
from planner.broadcast import ControlKind, BroadcastPolicy
from planner.types import Setpoints


class _Act:
    def __init__(self, variable_name, control_type):
        self.variable_name = variable_name
        self.control_type = control_type


class _FakeEnv:
    def __init__(self, actions):
        self._actions = actions
    @property
    def actions(self):
        return self._actions
    @property
    def unwrapped(self):
        return self


def test_classify_kind_by_substring():
    assert classify_kind("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint") is ControlKind.SAT
    assert classify_kind("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate") is ControlKind.FLOW
    assert classify_kind("chilled_water_loop_supply_temperature_setpoint") is ControlKind.CHWST


def test_classify_kind_unknown_raises():
    with pytest.raises(ValueError):
        classify_kind("some_other_actuator")


def test_bounds_for_each_kind():
    assert bounds_for(ControlKind.SAT) == (20.0, 26.0)
    assert bounds_for(ControlKind.FLOW) == (4.8, 13.8)
    assert bounds_for(ControlKind.CHWST) == (13.0, 19.0)


def test_action_spec_filters_agent_controlled_only_in_order():
    actions = [
        _Act("data hall gf 1a ite-1 cpu loading schedule", 3),
        _Act("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint", 2),
        _Act("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate", 2),
        _Act("chilled_water_supply_branch_1_on_off", 5),
        _Act("chilled_water_loop_supply_temperature_setpoint", 2),
    ]
    spec = action_spec_from_actions(actions)
    assert [e.kind for e in spec] == [ControlKind.SAT, ControlKind.FLOW, ControlKind.CHWST]
    assert (spec[0].lb, spec[0].ub) == (20.0, 26.0)


def test_mapper_from_env_builds_broadcastpolicy():
    actions = [
        _Act("data_hall_1f_2a_acu_1_supply_air_temperature_setpoint", 2),
        _Act("data_hall_1f_2a_acu_1_supply_air_mass_flow_rate", 2),
        _Act("chilled_water_loop_supply_temperature_setpoint", 2),
    ]
    bp = mapper_from_env(_FakeEnv(actions))
    assert isinstance(bp, BroadcastPolicy)
    out = bp.expand(Setpoints(sat_c=20.0, flow_kg_s=13.8, chwst_c=13.0))
    np.testing.assert_allclose(out, [-1.0, 1.0, -1.0])
