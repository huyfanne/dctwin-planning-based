import json
import math
from datetime import date

import pytest

from planner.kpi import OracleSettings, StepSample, aggregate_kpi
from planner.objective import ObjectiveWeights, score
from planner.recommendation import build_recommendation
from planner.tariff import Tariff, load_tariff
from planner.types import Setpoints, WeeklyKPI


def _sample(hvac_w: float) -> StepSample:
    # hvac via the total-minus-IT fallback: total = IT + hvac
    return StepSample(total_power_w=1000.0 + hvac_w, it_power_w=1000.0,
                      inlet_temps=[24.0])


def _kpi(energy=100.0, weighted=None):
    return WeeklyKPI(
        total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
        weighted_energy_cost=weighted,
    )


# ---------------------------------------------------------------- load_tariff

def test_load_tariff_absent_file_returns_none(tmp_path):
    assert load_tariff(str(tmp_path / "tariff.json")) is None


def test_load_tariff_valid_file(tmp_path):
    p = tmp_path / "tariff.json"
    rates = [0.1] * 24
    p.write_text(json.dumps({"kind": "price_usd_per_kwh", "rates": rates}))
    t = load_tariff(str(p))
    assert isinstance(t, Tariff)
    assert t.kind == "price_usd_per_kwh"
    assert t.rates == tuple(rates)
    assert len(t.rates) == 24


def test_load_tariff_wrong_length_returns_none(tmp_path):
    p = tmp_path / "tariff.json"
    p.write_text(json.dumps({"kind": "price", "rates": [0.1] * 23}))
    assert load_tariff(str(p)) is None


def test_load_tariff_non_numeric_returns_none(tmp_path):
    p = tmp_path / "tariff.json"
    p.write_text(json.dumps({"kind": "price", "rates": [0.1] * 23 + ["x"]}))
    assert load_tariff(str(p)) is None


def test_load_tariff_non_finite_returns_none(tmp_path):
    p = tmp_path / "tariff.json"
    p.write_text(json.dumps({"kind": "price", "rates": [0.1] * 23 + [float("inf")]}))
    assert load_tariff(str(p)) is None


def test_load_tariff_malformed_json_returns_none(tmp_path):
    p = tmp_path / "tariff.json"
    p.write_text("{not json")
    assert load_tariff(str(p)) is None


def test_load_tariff_missing_rates_returns_none(tmp_path):
    p = tmp_path / "tariff.json"
    p.write_text(json.dumps({"kind": "price"}))
    assert load_tariff(str(p)) is None


# ------------------------------------------------------- aggregate_kpi + cost

def test_no_tariff_weighted_cost_is_none_and_kpi_unchanged():
    samples = [_sample(1000.0), _sample(1000.0)]
    k = aggregate_kpi(samples, hours_per_step=0.25, settings=OracleSettings())
    assert k.weighted_energy_cost is None
    # behavior identical to today: same energy, same score path (raw energy)
    assert k.total_hvac_energy_kwh == 0.5
    assert score(k, ObjectiveWeights()) == k.total_hvac_energy_kwh


def test_flat_tariff_of_one_cost_equals_energy():
    samples = [_sample(1000.0)] * 10
    settings = OracleSettings(warmup_steps=0, tariff_rates=(1.0,) * 24)
    k = aggregate_kpi(samples, hours_per_step=0.25, settings=settings)
    assert k.weighted_energy_cost == pytest.approx(k.total_hvac_energy_kwh)


def test_step_hour_indexing_with_week_start_hour():
    # 2 steps of 1 h starting at hour 23 -> hours 23 then 0
    rates = [0.0] * 24
    rates[23] = 3.0
    rates[0] = 4.0
    settings = OracleSettings(warmup_steps=0, week_start_hour=23,
                              tariff_rates=tuple(rates))
    samples = [_sample(1000.0), _sample(1000.0)]   # 1 kWh per step at 1 h/step
    k = aggregate_kpi(samples, hours_per_step=1.0, settings=settings)
    assert k.weighted_energy_cost == pytest.approx(3.0 + 4.0)


def test_cost_uses_post_warmup_samples_like_energy():
    # warmup of 6 dropped; the 2 scored steps land on hours 0 and 1
    rates = [0.0] * 24
    rates[0] = 5.0
    rates[1] = 7.0
    settings = OracleSettings(warmup_steps=6, week_start_hour=0,
                              tariff_rates=tuple(rates))
    samples = [_sample(9000.0)] * 6 + [_sample(1000.0), _sample(1000.0)]
    k = aggregate_kpi(samples, hours_per_step=1.0, settings=settings)
    assert k.total_hvac_energy_kwh == pytest.approx(2.0)      # warmup excluded
    assert k.weighted_energy_cost == pytest.approx(5.0 + 7.0)


def test_peak_tariff_ranks_peak_heavy_profile_worse():
    # same total energy, but profile A burns it during peak hours 12-17
    rates = [1.0] * 24
    for h in range(12, 18):
        rates[h] = 2.0
    settings = OracleSettings(warmup_steps=0, tariff_rates=tuple(rates))
    peak = [_sample(2000.0 if 12 <= h < 18 else 500.0) for h in range(24)]
    offpeak = [_sample(2000.0 if h < 6 else 500.0) for h in range(24)]
    k_peak = aggregate_kpi(peak, hours_per_step=1.0, settings=settings)
    k_off = aggregate_kpi(offpeak, hours_per_step=1.0, settings=settings)
    assert k_peak.total_hvac_energy_kwh == pytest.approx(k_off.total_hvac_energy_kwh)
    assert k_peak.weighted_energy_cost > k_off.weighted_energy_cost
    w = ObjectiveWeights()
    assert score(k_peak, w) > score(k_off, w)


def test_empty_samples_weighted_cost_none():
    k = aggregate_kpi([], 0.25, OracleSettings(tariff_rates=(1.0,) * 24))
    assert k.weighted_energy_cost is None
    assert k.feasible is False


# ------------------------------------------------------------------ objective

def test_score_uses_weighted_cost_when_present():
    w = ObjectiveWeights()
    assert score(_kpi(energy=100.0, weighted=50.0), w) == 50.0
    assert score(_kpi(energy=100.0, weighted=None), w) == 100.0


def test_score_weighted_cost_keeps_penalties():
    w = ObjectiveWeights(lambda_temp=2.0)
    k = WeeklyKPI(
        total_hvac_energy_kwh=100.0, pue_mean=1.2, inlet_temp_max=24.0,
        inlet_violation_steps=0, rh_violation_steps=0, feasible=True,
        inlet_excess_degc_steps=3.0, weighted_energy_cost=50.0,
    )
    assert score(k, w) == 50.0 + 2.0 * 3.0


def test_score_non_finite_weighted_cost_is_infeasible():
    from planner.objective import INFEASIBLE
    assert score(_kpi(weighted=float("inf")), ObjectiveWeights()) == INFEASIBLE
    assert score(_kpi(weighted=float("nan")), ObjectiveWeights()) == INFEASIBLE


# ------------------------------------------------------------- recommendation

def test_recommendation_surfaces_weighted_cost_and_kind():
    rec = build_recommendation(
        setpoints=Setpoints(24.0, 8.0, 17.0),
        kpi=_kpi(energy=100.0, weighted=42.0),
        week_start=date(2026, 6, 15), days=7,
        forecast_method="persistence", search_meta={},
        tariff_kind="price_usd_per_kwh",
    )
    assert rec["predicted_kpis"]["weighted_energy_cost"] == 42.0
    assert rec["predicted_kpis"]["tariff_kind"] == "price_usd_per_kwh"


def test_recommendation_omits_tariff_keys_when_absent():
    rec = build_recommendation(
        setpoints=Setpoints(24.0, 8.0, 17.0),
        kpi=_kpi(energy=100.0, weighted=None),
        week_start=date(2026, 6, 15), days=7,
        forecast_method="persistence", search_meta={},
    )
    assert "weighted_energy_cost" not in rec["predicted_kpis"]
    assert "tariff_kind" not in rec["predicted_kpis"]


# ---------------------------------------------------------------- back-compat

def test_weeklykpi_positional_construction_still_works():
    # existing call sites build WeeklyKPI positionally with 6 args; the new
    # field must stay keyword-only-safe (appended last, default None)
    k = WeeklyKPI(0.0, 1.0, 0.0, 0, 0, True)
    assert k.weighted_energy_cost is None


def test_weighted_cost_math_floor_hour_step():
    # 0.25 h steps: floor(i*0.25) keeps the first 4 steps in hour 0, next 4 in hour 1
    rates = [0.0] * 24
    rates[0] = 1.0
    rates[1] = 10.0
    settings = OracleSettings(warmup_steps=0, tariff_rates=tuple(rates))
    samples = [_sample(1000.0)] * 8   # 0.25 kWh per step
    k = aggregate_kpi(samples, hours_per_step=0.25, settings=settings)
    assert k.weighted_energy_cost == pytest.approx(4 * 0.25 * 1.0 + 4 * 0.25 * 10.0)
    assert math.isfinite(k.weighted_energy_cost)
