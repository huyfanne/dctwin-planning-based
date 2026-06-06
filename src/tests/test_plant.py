from pathlib import Path

import opyplus as op
from planner.plant import Perturbation, PlantConfig, DEFAULT_PLANT, apply_perturbation, build_plant_prototxt

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
