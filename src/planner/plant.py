"""Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled
physical parameters (fan efficiency, coil UA). Same opyplus path dctwin uses."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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


def load_plant_config(path: str | Path = "data/plant_calibration.json") -> PlantConfig:
    """The data-driven believed plant state (Stage 6 #9): DEFAULT_PLANT with the
    deploy loop's fitted factors (planner.recalibrator proposals persisted by
    webapp/jobs) merged in. A fitted (table, field) REPLACES the matching
    DEFAULT_PLANT perturbation; unmatched fitted entries are appended; the rest of
    DEFAULT_PLANT is kept. Absent (or unreadable) file -> DEFAULT_PLANT exactly,
    so cold start is provably today's behavior."""
    p = Path(path)
    if not p.exists():
        return DEFAULT_PLANT
    try:
        entries = json.loads(p.read_text()).get("perturbations", [])
        fitted = {(str(e["table"]), str(e["field"])): float(e["factor"]) for e in entries}
    except Exception:  # noqa: BLE001 - a malformed file must never break planning
        logger.warning("unreadable plant calibration %s; using DEFAULT_PLANT", path)
        return DEFAULT_PLANT
    default_keys = {(q.table, q.field) for q in DEFAULT_PLANT.perturbations}
    merged = [Perturbation(q.table, q.field, fitted.get((q.table, q.field), q.factor))
              for q in DEFAULT_PLANT.perturbations]
    merged += [Perturbation(t, f, v) for (t, f), v in fitted.items()
               if (t, f) not in default_keys]
    return PlantConfig(tuple(merged))


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
