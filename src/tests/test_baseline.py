import pandas as pd

from planner.baseline import as_operated_setpoints, BaselineColumns
from planner.types import DEFAULT_SEARCH_SPACE


def _df():
    # Two CRAH supply-temp sensors, one CHWST sensor, one fan-speed sensor (fraction).
    return pd.DataFrame({
        "1F_..._CRACW01_AirSupplyTemperature": [22.0, 24.0, 23.0],   # median 23
        "1F_..._CRACW02_AirSupplyTemperature": [23.0, 23.0, 23.0],   # median 23
        "..._CHILLER01_ChilledWaterSupplyTemperature": [15.0, 17.0, 16.0],  # median 16
        "1F_..._CRACW01_FanSpeed": [0.5, 0.5, 0.5],                  # median 0.5
    })


_COLS = BaselineColumns(
    sat_supply_temp=r"CRACW\d+_AirSupplyTemperature$",
    chwst_supply_temp=r"CHILLER\d+_ChilledWaterSupplyTemperature$",
    fan_speed=r"CRACW\d+_FanSpeed$",
)


def test_as_operated_setpoints_uses_column_medians():
    sp = as_operated_setpoints(_df(), DEFAULT_SEARCH_SPACE, _COLS,
                               design_flow_kg_s_per_acu=9.6)
    assert sp.sat_c == 23.0
    assert sp.chwst_c == 16.0
    # flow = median fan speed (0.5) * design 9.6 = 4.8 -> within [4.8, 13.8]
    assert sp.flow_kg_s == 4.8


def test_as_operated_setpoints_clips_to_search_space():
    df = _df()
    df["1F_..._CRACW01_AirSupplyTemperature"] = [30.0, 30.0, 30.0]   # above SAT ub 26
    df["1F_..._CRACW01_FanSpeed"] = [2.0, 2.0, 2.0]                  # *9.6 = 19.2 > flow ub 13.8
    sp = as_operated_setpoints(df, DEFAULT_SEARCH_SPACE, _COLS,
                               design_flow_kg_s_per_acu=9.6)
    assert sp.sat_c == DEFAULT_SEARCH_SPACE.sat.ub      # clipped to 26
    assert sp.flow_kg_s == DEFAULT_SEARCH_SPACE.flow.ub  # clipped to 13.8


def test_as_operated_setpoints_handles_percent_fan_speed():
    # Real telemetry stores fan speed as a percent (0-100); fan_speed_max=100 scales it.
    df = _df()
    df["1F_..._CRACW01_FanSpeed"] = [50.0, 50.0, 50.0]   # 50% -> 0.5 fraction
    sp = as_operated_setpoints(df, DEFAULT_SEARCH_SPACE, _COLS,
                               design_flow_kg_s_per_acu=13.8, fan_speed_max=100.0)
    assert sp.flow_kg_s == 6.9   # 0.5 * 13.8


def test_as_operated_setpoints_falls_back_to_midrange_when_no_fan_speed():
    df = _df().drop(columns=["1F_..._CRACW01_FanSpeed"])
    sp = as_operated_setpoints(df, DEFAULT_SEARCH_SPACE, _COLS,
                               design_flow_kg_s_per_acu=9.6)
    mid = (DEFAULT_SEARCH_SPACE.flow.lb + DEFAULT_SEARCH_SPACE.flow.ub) / 2
    assert sp.flow_kg_s == mid
    assert sp.sat_c == 23.0   # SAT/CHWST still derived
