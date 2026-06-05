from planner.kpi import StepSample, OracleSettings, aggregate_kpi


def _sample(total, it, inlets, rhs=None, zones=None):
    return StepSample(
        total_power_w=total, it_power_w=it,
        inlet_temps=inlets, inlet_rhs=rhs or [45.0], zone_temps=zones or [32.0],
    )


def test_energy_is_hvac_power_times_hours():
    s = [_sample(2000.0, 1000.0, [24.0]), _sample(2000.0, 1000.0, [24.0])]
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings())
    assert k.total_hvac_energy_kwh == 0.5


def test_pue_mean():
    s = [_sample(2400.0, 2000.0, [24.0])]
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings())
    assert k.pue_mean == 1.2


def test_inlet_violation_counts_steps_over_cap():
    s = [_sample(2000.0, 1000.0, [25.0, 26.5]),
         _sample(2000.0, 1000.0, [24.0, 25.0])]
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings(inlet_cap=26.0))
    assert k.inlet_violation_steps == 1
    assert k.inlet_temp_max == 26.5


def test_inlet_excess_uses_soft_margin():
    s = [_sample(2000.0, 1000.0, [26.0])]
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(inlet_cap=26.0, inlet_soft_margin=1.0))
    assert k.inlet_excess_degc_steps == 1.0


def test_rh_violation_and_excursion():
    s = [_sample(2000.0, 1000.0, [24.0], rhs=[25.0]),
         _sample(2000.0, 1000.0, [24.0], rhs=[65.0])]
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(rh_min=30.0, rh_max=60.0))
    assert k.rh_violation_steps == 2
    assert k.rh_excursion_steps == 10.0


def test_zone_band_excursion():
    s = [_sample(2000.0, 1000.0, [24.0], zones=[34.0])]
    k = aggregate_kpi(s, hours_per_step=0.25,
                      settings=OracleSettings(zone_target=32.0, zone_band=1.0))
    assert k.zone_temp_band_steps == 1.0


def test_feasible_true_on_successful_aggregation():
    k = aggregate_kpi([_sample(2000.0, 1000.0, [24.0])], 0.25, OracleSettings())
    assert k.feasible is True


def test_empty_samples_is_infeasible():
    k = aggregate_kpi([], 0.25, OracleSettings())
    assert k.feasible is False


def test_pue_mean_ignores_zero_it_steps():
    # only the it>0 step counts toward the mean: total/it = 2400/2000 = 1.2
    s = [_sample(2400.0, 2000.0, [24.0]), _sample(1000.0, 0.0, [24.0])]
    k = aggregate_kpi(s, hours_per_step=0.25, settings=OracleSettings())
    assert k.pue_mean == 1.2


def test_empty_samples_sentinels():
    import math
    k = aggregate_kpi([], 0.25, OracleSettings())
    assert k.feasible is False
    assert math.isinf(k.total_hvac_energy_kwh)
    assert k.inlet_violation_steps >= 10 ** 9
