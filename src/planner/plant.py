"""Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled
physical parameters (fan efficiency, coil UA). Same opyplus path dctwin uses."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Perturbation:
    table: str   # opyplus table attr, e.g. "Fan_VariableVolume"
    field: str   # lowercased field, e.g. "fan_total_efficiency"
    factor: float


@dataclass(frozen=True)
class PlantConfig:
    perturbations: tuple[Perturbation, ...]


# Degraded fan efficiency + fouled cooling coil (reduced chilled-water flow) ->
# the plant runs hotter and uses more energy than the (nominal) twin predicts.
# Both objects exist in the GDS IDF.
DEFAULT_PLANT = PlantConfig((
    Perturbation("Fan_VariableVolume", "fan_total_efficiency", 0.93),
    Perturbation("Coil_Cooling_Water", "design_water_flow_rate", 0.85),
))


def apply_perturbation(idf_in: str | Path, plant: PlantConfig, idf_out: str | Path) -> str:
    """Scale the configured numeric fields and save a perturbed IDF copy.

    Non-numeric values (e.g. "autosize") are left untouched.
    """
    import opyplus as op

    epm = op.Epm.load(idf_in)
    for p in plant.perturbations:
        table = getattr(epm, p.table)
        for rec in table:
            val = rec[p.field]
            if isinstance(val, (int, float)):
                rec[p.field] = val * p.factor
    Path(idf_out).parent.mkdir(parents=True, exist_ok=True)
    epm.save(idf_out)
    return idf_out


def build_plant_prototxt(base_prototxt: str | Path, plant: PlantConfig, out_dir: str | Path) -> str:
    """Write a perturbed IDF + a DT prototxt copy that points at it. Mirrors
    week_config.write_week_config. Lazy dctwin import keeps the pure logic testable."""
    from dctwin.utils import read_engine_config
    from google.protobuf import text_format

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = read_engine_config(str(base_prototxt))
    env_cfg = getattr(cfg, cfg.WhichOneof("EnvConfig"))

    idf_out = str((out / "plant.idf").resolve())
    apply_perturbation(env_cfg.model_file, plant, idf_out)
    env_cfg.model_file = idf_out

    proto_out = str(out / "plant.prototxt")
    Path(proto_out).write_text(text_format.MessageToString(cfg))
    return proto_out
