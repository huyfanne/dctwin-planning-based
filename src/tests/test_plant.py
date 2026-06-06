import opyplus as op
from planner.plant import Perturbation, PlantConfig, DEFAULT_PLANT, apply_perturbation

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
