from planner.monitor import MonitorSpec, discover_monitor


class _Obs:
    def __init__(self, variable_name):
        self.variable_name = variable_name


class _FakeEnv:
    def __init__(self, names):
        self._obs = [_Obs(n) for n in names]
    @property
    def observations(self):
        return self._obs
    @property
    def unwrapped(self):
        return self


def test_discover_classifies_observations():
    env = _FakeEnv([
        "total power",
        "total it power",
        "data hall 1f 2a ite-1 inlet dry-bulb temperature",
        "data hall 1f 2a ite-2 inlet dry-bulb temperature",
        "data hall 1f 2a ite-1 inlet relative humidity",
        "data hall 1f 2a air temperature",
        "data hall 1f 2a acu-1 fan power consumption",  # ignored
    ])
    m = discover_monitor(env)
    assert m.total_power_name == "total power"
    assert m.it_power_name == "total it power"
    assert len(m.inlet_temp_names) == 2
    assert m.inlet_rh_names == ["data hall 1f 2a ite-1 inlet relative humidity"]
    assert m.zone_temp_names == ["data hall 1f 2a air temperature"]


def test_discover_requires_power_observations():
    import pytest
    env = _FakeEnv(["data hall 1f 2a ite-1 inlet dry-bulb temperature"])
    with pytest.raises(ValueError):
        discover_monitor(env)
