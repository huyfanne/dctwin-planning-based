import math

from planner.types import Setpoints, Bounds, SearchSpace, WeeklyKPI, DEFAULT_SEARCH_SPACE


def test_bounds_clip_inside_and_outside():
    b = Bounds(20.0, 26.0)
    assert b.clip(23.0) == 23.0
    assert b.clip(10.0) == 20.0
    assert b.clip(99.0) == 26.0


def test_setpoints_as_tuple_order():
    s = Setpoints(sat_c=24.0, flow_kg_s=8.0, chwst_c=17.0)
    assert s.as_tuple() == (24.0, 8.0, 17.0)


def test_search_space_clip_clamps_all_dims():
    s = Setpoints(sat_c=99.0, flow_kg_s=0.0, chwst_c=99.0)
    clipped = DEFAULT_SEARCH_SPACE.clip(s)
    assert clipped == Setpoints(26.0, 4.8, 19.0)


def test_default_search_space_matches_gds_bounds():
    assert DEFAULT_SEARCH_SPACE.sat == Bounds(20.0, 26.0)
    assert DEFAULT_SEARCH_SPACE.flow == Bounds(4.8, 13.8)
    assert DEFAULT_SEARCH_SPACE.chwst == Bounds(13.0, 19.0)


def test_weekly_kpi_defaults():
    k = WeeklyKPI(
        total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
    )
    assert k.inlet_excess_degc_steps == 0.0
    assert k.zone_temp_band_steps == 0.0
