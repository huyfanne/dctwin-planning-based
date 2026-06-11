import json
from pathlib import Path

import opyplus as op
from planner.plant import (Perturbation, PlantConfig, DEFAULT_PLANT, apply_perturbation,
                           build_plant_prototxt, load_plant_config)

# Stable fan name present in building.idf; used to avoid opyplus reordering fans
# after a save/load round-trip (opyplus sorts alphabetically on write).
_STABLE_FAN = "data hall gf 1a acu-1 fan"


def _first_fan_efficiency(idf_path):
    epm = op.Epm.load(idf_path)
    return epm.Fan_VariableVolume.select(lambda r: r.name == _STABLE_FAN).one().fan_total_efficiency


def test_apply_perturbation_scales_fan_efficiency(tmp_path):
    base = "models/idf/building.idf"
    before = _first_fan_efficiency(base)
    out = str(tmp_path / "plant.idf")
    cfg = PlantConfig((Perturbation("Fan_VariableVolume", "fan_total_efficiency", 0.5),))
    apply_perturbation(base, cfg, out)
    after = _first_fan_efficiency(out)
    assert after == before * 0.5


def test_default_plant_has_fan_and_coil_perturbations():
    tables = {p.table for p in DEFAULT_PLANT.perturbations}
    assert tables == {"Fan_VariableVolume", "Coil_Cooling_Water"}


def test_default_plant_apply_perturbation_scales_fan_and_coil(tmp_path):
    out = str(tmp_path / "plant.idf")
    apply_perturbation("models/idf/building.idf", DEFAULT_PLANT, out)
    epm = op.Epm.load(out)
    base = op.Epm.load("models/idf/building.idf")
    fan = epm.Fan_VariableVolume.select(lambda r: r.name == _STABLE_FAN).one()
    fan0 = base.Fan_VariableVolume.select(lambda r: r.name == _STABLE_FAN).one()
    assert fan.fan_total_efficiency == fan0.fan_total_efficiency * 0.93
    coil_name = "data hall gf 1a acu-1 cooling coil"
    coil = epm.Coil_Cooling_Water.select(lambda r: r.name == coil_name).one()
    coil0 = base.Coil_Cooling_Water.select(lambda r: r.name == coil_name).one()
    assert coil.design_water_flow_rate == coil0.design_water_flow_rate * 0.85


def test_load_plant_config_absent_file_is_default_plant(tmp_path):
    # Cold start (#9): no data/plant_calibration.json -> DEFAULT_PLANT exactly,
    # so the robust ensemble center is provably unchanged.
    assert load_plant_config(str(tmp_path / "absent.json")) == DEFAULT_PLANT


def test_load_plant_config_fitted_factor_replaces_matching_perturbation(tmp_path):
    p = tmp_path / "plant_calibration.json"
    p.write_text(json.dumps({"perturbations": [
        {"table": "Fan_VariableVolume", "field": "fan_total_efficiency", "factor": 0.9},
    ], "basis": {"n_weeks": 4}}))
    cfg = load_plant_config(str(p))
    by_key = {(q.table, q.field): q.factor for q in cfg.perturbations}
    assert by_key[("Fan_VariableVolume", "fan_total_efficiency")] == 0.9      # replaced
    assert by_key[("Coil_Cooling_Water", "design_water_flow_rate")] == 0.85   # kept
    assert len(cfg.perturbations) == len(DEFAULT_PLANT.perturbations)


def test_load_plant_config_extends_with_unmatched_perturbations(tmp_path):
    p = tmp_path / "plant_calibration.json"
    p.write_text(json.dumps({"perturbations": [
        {"table": "Pump_VariableSpeed", "field": "motor_efficiency", "factor": 0.95},
    ]}))
    cfg = load_plant_config(str(p))
    n = len(DEFAULT_PLANT.perturbations)
    assert cfg.perturbations[:n] == DEFAULT_PLANT.perturbations               # all kept
    assert cfg.perturbations[n] == Perturbation("Pump_VariableSpeed", "motor_efficiency", 0.95)


def test_load_plant_config_malformed_file_falls_back_to_default(tmp_path):
    p = tmp_path / "plant_calibration.json"
    p.write_text("{definitely not json")
    assert load_plant_config(str(p)) == DEFAULT_PLANT


def test_build_plant_prototxt_points_at_perturbed_idf(tmp_path):
    out_proto = build_plant_prototxt(
        "configs/dt/dt.prototxt", DEFAULT_PLANT, str(tmp_path))
    assert Path(out_proto).exists()
    from dctwin.utils import read_engine_config
    cfg = read_engine_config(out_proto)
    env = getattr(cfg, cfg.WhichOneof("EnvConfig"))
    assert Path(env.model_file).is_absolute()
    assert Path(env.model_file).name == "plant.idf"
    assert Path(env.model_file).exists()
