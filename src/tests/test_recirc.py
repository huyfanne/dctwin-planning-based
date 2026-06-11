import json
import random
import sqlite3

import pytest

import fit_recirc
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.recirc import (
    DEFAULT_RECIRC_CONFIG,
    RecircAwareEvaluator,
    estimate_recirc_fraction,
    flow_shortfall_recirc,
    inlet_with_recirc,
    load_recirc_config,
)
from planner.types import Setpoints


# ---- inlet_with_recirc -------------------------------------------------------------

def test_inlet_with_recirc_identity_at_r0():
    # r_eff == r0 (flow >= demand) must be the EXACT identity: legacy behavior unchanged.
    assert inlet_with_recirc(24.0, 32.0, 0.10, 0.10) == 24.0


def test_inlet_with_recirc_adds_shortfall_correction():
    # correction = (r_eff - r0) * (zone - inlet) = 0.1 * 8 = 0.8
    assert inlet_with_recirc(24.0, 32.0, 0.10, 0.20) == pytest.approx(24.8)


def test_inlet_with_recirc_is_conservative_only():
    # zone cooler than the inlet -> no relief (max(0, zone - inlet) clamps)
    assert inlet_with_recirc(33.0, 32.0, 0.10, 0.30) == 33.0
    # r_eff < r0 (defensive: should not happen) must never LOWER the predicted inlet
    assert inlet_with_recirc(24.0, 32.0, 0.20, 0.10) == 24.0


# ---- flow_shortfall_recirc ---------------------------------------------------------

def test_flow_shortfall_identity_at_or_above_demand():
    assert flow_shortfall_recirc(0.10, 6.0, 6.0) == 0.10
    assert flow_shortfall_recirc(0.10, 9.0, 6.0) == 0.10


def test_flow_shortfall_rises_only_below_demand():
    # r_eff = r0 + k*(1 - flow/demand): 0.10 + 0.5*0.2 = 0.20
    assert flow_shortfall_recirc(0.10, 4.8, 6.0) == pytest.approx(0.20)
    assert flow_shortfall_recirc(0.10, 3.0, 6.0) == pytest.approx(0.35)


def test_flow_shortfall_clipped_at_r_max():
    assert flow_shortfall_recirc(0.45, 0.0, 6.0) == 0.5
    assert flow_shortfall_recirc(0.10, 0.0, 6.0, k=2.0, r_max=0.4) == 0.4


# ---- estimate_recirc_fraction ------------------------------------------------------

def test_estimate_recovers_synthetic_r():
    rng = random.Random(42)
    r_true = 0.18
    rows = []
    for _ in range(200):
        supply = rng.uniform(20.0, 23.0)
        ret = supply + rng.uniform(5.0, 12.0)
        inlet = supply + r_true * (ret - supply) + rng.gauss(0.0, 0.05)
        rows.append((inlet, supply, ret))
    est = estimate_recirc_fraction(rows)
    assert est["n"] == 200
    assert abs(est["r"] - r_true) <= 0.02


def test_estimate_discards_degenerate_return_supply_deltas():
    rows = [
        (22.0, 20.0, 30.0),   # r = 0.2, kept
        (20.5, 20.0, 20.9),   # |Tret - Tsup| = 0.9 < 1 C -> discarded
        (20.0, 20.0, 20.0),   # zero delta -> discarded (no division by ~0)
    ]
    est = estimate_recirc_fraction(rows)
    assert est["n"] == 1
    assert est["r"] == pytest.approx(0.2)


def test_estimate_clips_to_physical_bounds():
    assert estimate_recirc_fraction([(29.0, 20.0, 30.0)])["r"] == 0.5   # raw 0.9
    assert estimate_recirc_fraction([(19.0, 20.0, 30.0)])["r"] == 0.0   # raw -0.1


def test_estimate_per_rack_medians():
    rows = [
        (22.0, 20.0, 30.0, "ite-1"),
        (23.0, 20.0, 30.0, "ite-2"),
        (22.0, 20.0, 30.0, "ite-2"),
    ]
    est = estimate_recirc_fraction(rows)
    assert est["r_per_rack"]["ite-1"] == pytest.approx(0.2)
    assert est["r_per_rack"]["ite-2"] == pytest.approx(0.25)   # median of [0.3, 0.2]


def test_estimate_empty_rows():
    assert estimate_recirc_fraction([]) == {"r": None, "n": 0, "r_per_rack": {}}


# ---- load_recirc_config ------------------------------------------------------------

def test_load_recirc_config_defaults_when_absent(tmp_path):
    cfg = load_recirc_config(str(tmp_path / "absent.json"))
    assert cfg == {"r0": 0.10, "demand_kg_s": 4.8, "k": 0.5}


def test_load_recirc_config_merges_file_over_defaults(tmp_path):
    p = tmp_path / "recirc.json"
    p.write_text(json.dumps({"r0": 0.18, "demand_kg_s": None}))
    # explicit null is "not calibrated" -> the default, never a TypeError downstream
    assert load_recirc_config(str(p)) == {"r0": 0.18, "demand_kg_s": 4.8, "k": 0.5}


# ---- RecircAwareEvaluator ----------------------------------------------------------

def test_wrapper_identity_with_default_config(tmp_path):
    # default demand == flow.lb: every in-bounds candidate has flow >= demand -> r_eff == r0
    cands = [Setpoints(24.0, 4.8, 17.0), Setpoints(22.0, 9.0, 15.0)]
    wrapped = RecircAwareEvaluator(MockEvaluator(), load_recirc_config(str(tmp_path / "x.json")))
    assert wrapped.evaluate(cands) == MockEvaluator().evaluate(cands)


def test_wrapper_penalizes_only_low_flow_candidates():
    inner = MockEvaluator()
    wrapped = RecircAwareEvaluator(inner, {"r0": 0.10, "demand_kg_s": 6.0, "k": 0.5})
    low, high = Setpoints(24.0, 4.8, 13.0), Setpoints(24.0, 7.8, 13.0)
    kpi_low, kpi_high = wrapped.evaluate([low, high])
    raw_low, raw_high = MockEvaluator().evaluate([low, high])
    # flow 4.8 vs demand 6.0 -> r_eff = 0.2 -> inlet + 0.1*(32 - inlet)
    expected = raw_low.inlet_temp_max + 0.1 * (32.0 - raw_low.inlet_temp_max)
    assert kpi_low.inlet_temp_max == pytest.approx(expected)
    assert kpi_low.inlet_temp_max > raw_low.inlet_temp_max
    assert kpi_high == raw_high                     # flow >= demand: untouched KPI


def test_wrapper_flags_violation_when_recirc_pushes_over_cap():
    surface = MockSurface(sat_opt=26.0, flow_opt=4.8, chwst_opt=13.0, inlet_base=20.0)
    inner = MockEvaluator(surface)
    wrapped = RecircAwareEvaluator(inner, {"r0": 0.10, "demand_kg_s": 6.0, "k": 0.5})
    sp = Setpoints(26.0, 4.8, 13.0)                  # inlet exactly 26.0 = the cap
    [raw] = MockEvaluator(surface).evaluate([sp])
    assert raw.inlet_temp_max == 26.0 and raw.inlet_violation_steps == 0
    [kpi] = wrapped.evaluate([sp])
    assert kpi.inlet_temp_max == pytest.approx(26.6)         # 26 + 0.1*(32-26)
    assert kpi.inlet_violation_steps >= 1                    # crossed the hard cap
    # soft excess (accrues from cap-1) absorbed the max-step delta: 1.6 vs raw 1.0
    assert kpi.inlet_excess_degc_steps == pytest.approx(1.6)


def test_wrapper_forwards_on_result_and_passes_through_api():
    inner = MockEvaluator()
    wrapped = RecircAwareEvaluator(inner, dict(DEFAULT_RECIRC_CONFIG))
    ticks = []
    wrapped.evaluate([Setpoints(24.0, 8.0, 17.0)], on_result=lambda: ticks.append(1))
    assert ticks == [1]
    # __getattr__ passthrough: schedules/replay/counters resolve on the wrapped evaluator
    assert hasattr(wrapped, "evaluate_schedules")
    assert wrapped.call_count == inner.call_count == 1
    kpi, samples = wrapped.replay_with_trajectory(Setpoints(24.0, 8.0, 17.0))
    assert len(samples) == 8


# ---- fit_recirc CLI ----------------------------------------------------------------

def _write_csv(path, r=0.2, supplies=(20.0, 21.0, 22.0), delta=10.0):
    lines = ["inlet_c,supply_c,return_c"]
    for s in supplies:
        lines.append(f"{s + r * delta},{s},{s + delta}")
    path.write_text("\n".join(lines) + "\n")


def _seed_telemetry_db(path, snapshots):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE telemetry (ts REAL, point TEXT, value REAL)")
    for ts, points in snapshots:
        con.executemany("INSERT INTO telemetry VALUES (?, ?, ?)",
                        [(ts, k, v) for k, v in points.items()])
    con.commit()
    con.close()


def test_fit_recirc_csv_fit_and_write(tmp_path, capsys):
    csv_path = tmp_path / "telemetry.csv"
    _write_csv(csv_path, r=0.2)
    out = tmp_path / "recirc.json"
    est = fit_recirc.main(["--csv", str(csv_path), "--write", "--out", str(out)])
    assert est["r"] == pytest.approx(0.2) and est["n"] == 3
    assert "fitted r" in capsys.readouterr().out
    cfg = json.loads(out.read_text())
    assert cfg["r0"] == pytest.approx(0.2)
    assert cfg["demand_kg_s"] == 4.8 and cfg["k"] == 0.5    # never invented by the r fit


def test_fit_recirc_write_preserves_calibrated_demand(tmp_path):
    out = tmp_path / "recirc.json"
    out.write_text(json.dumps({"r0": 0.10, "demand_kg_s": 6.5, "k": 0.4}))
    csv_path = tmp_path / "telemetry.csv"
    _write_csv(csv_path, r=0.2)
    fit_recirc.main(["--csv", str(csv_path), "--write", "--out", str(out)])
    cfg = json.loads(out.read_text())
    assert cfg["demand_kg_s"] == 6.5 and cfg["k"] == 0.4    # demand calibration untouched
    assert cfg["r0"] == pytest.approx(0.2)


def test_fit_recirc_csv_constant_return_fallback(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    csv_path.write_text("inlet_c,supply_c\n22.0,20.0\n")
    est = fit_recirc.main(["--csv", str(csv_path), "--return-c", "30.0"])
    assert est["n"] == 1 and est["r"] == pytest.approx(0.2)


def test_fit_recirc_sqlite_with_constant_return(tmp_path):
    db = tmp_path / "telemetry.sqlite"
    _seed_telemetry_db(db, [
        (1000.0, {"held/sat_c": 20.0, "rack_inlet_c/ite-1": 22.4,
                  "rack_inlet_c/ite-2": 22.4, "pue": 1.4}),
        (1005.0, {"held/sat_c": 21.0, "rack_inlet_c/ite-1": 23.2,
                  "rack_inlet_c/ite-2": 23.2}),
    ])
    est = fit_recirc.main(["--db", str(db), "--return-c", "32.0"])
    assert est["n"] == 4
    assert est["r"] == pytest.approx(0.2)
    assert set(est["r_per_rack"]) == {"ite-1", "ite-2"}


def test_fit_recirc_sqlite_with_return_point(tmp_path):
    db = tmp_path / "telemetry.sqlite"
    _seed_telemetry_db(db, [
        (1000.0, {"held/sat_c": 20.0, "return_air_c": 30.0, "rack_inlet_c/ite-1": 21.8}),
        (1005.0, {"return_air_c": 30.0, "rack_inlet_c/ite-1": 21.8}),  # no supply -> skipped
    ])
    est = fit_recirc.main(["--db", str(db), "--return-point", "return_air_c"])
    assert est["n"] == 1 and est["r"] == pytest.approx(0.18)


def test_fit_recirc_errors_when_no_usable_rows(tmp_path):
    db = tmp_path / "telemetry.sqlite"
    _seed_telemetry_db(db, [(1000.0, {"held/sat_c": 20.0, "rack_inlet_c/ite-1": 20.1})])
    with pytest.raises(SystemExit):
        fit_recirc.main(["--db", str(db), "--return-c", "20.5"])   # delta 0.5 C: all discarded
