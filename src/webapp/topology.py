"""topology.py — pure, deterministic hall topology builder.

Reads the GDS assets (building.json + dt.prototxt) to derive:
  - crahs : 22 AGENT_CONTROLLED ACUs for hall 1F 2A, placed along two long walls
  - rack_rows : deterministic rows down the hall middle, alternating cold/hot aisles
  - plant : chiller / coolingTower / pump counts from building.json coolingModels
  - hall : name + schematic bounding box [30, 20, 4] m
  - links : CHW pipe links from plant to each CRAH

No dctwin imports; no side effects.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_crahs_from_prototxt(prototxt_path: str, hall: str) -> int:
    """Count AGENT_CONTROLLED ACU supply-air-temperature-setpoint actions for `hall`."""
    hall_slug = hall.lower().replace(" ", "_")
    pattern = re.compile(
        r'variable_name\s*:\s*"data_hall_'
        + re.escape(hall_slug)
        + r'_acu_\d+_supply_air_temperature_setpoint"'
    )
    text = Path(prototxt_path).read_text()
    return len(pattern.findall(text))


def _read_plant_counts(building_json: str) -> dict:
    """Read chiller / coolingTower / pump counts from building.json coolingModels."""
    data = json.loads(Path(building_json).read_text())
    cm = data["models"]["coolingModels"]
    return {
        "chiller": len(cm.get("chillers", {})),
        "coolingTower": len(cm.get("coolingTowers", {})),
        "pumps": len(cm.get("pumps", {})),
    }


def _rack_rows_from_room2ite(building_json: str, hall: str) -> List[dict]:
    """Derive rack rows for the hall from room2ite_map.json (sibling of building.json).

    Falls back to a fixed 6-row layout of 10 racks each if the map is absent
    or the hall is not found.  Positions are fully deterministic.
    """
    hall_name_canon = f"Data Hall {hall.upper()}"
    room2ite_path = Path(building_json).parent.parent / "configs" / "dt" / "room2ite_map.json"

    n_ite = 0
    if room2ite_path.exists():
        r2i = json.loads(room2ite_path.read_text())
        # case-insensitive key match
        for key, val in r2i.items():
            if key.lower() == hall_name_canon.lower():
                n_ite = len(val)
                break

    # Layout: 6 rows of 10 racks regardless (n_ite is informational).
    # If we know n_ite, distribute evenly across 6 rows (minimum 1).
    n_rows = 6
    nracks_per_row = max(1, (n_ite // n_rows) if n_ite >= n_rows else 10)

    # Hall schematic size: 30 × 20 m (x × y).  Rows run along x-axis.
    # Rows are placed in the middle 10 m (y: 5..15), spaced 1.67 m apart.
    hall_w, hall_d = 30.0, 20.0
    row_spacing = (hall_d - 10.0) / max(n_rows - 1, 1)
    y_start = 5.0

    rows: List[dict] = []
    for i in range(n_rows):
        aisle = "cold" if i % 2 == 0 else "hot"
        y = round(y_start + i * row_spacing, 3)
        rows.append({
            "id": f"row-{i + 1}",
            "aisle": aisle,
            "nracks": nracks_per_row,
            "pos": [hall_w / 2.0, y, 0.0],  # centre of row
        })
    return rows


def _place_crahs(n: int, hall_w: float, hall_d: float, hall_h: float) -> List[dict]:
    """Place n CRAHs deterministically along the two long walls (y=0 and y=hall_d).

    Split evenly: first half on y=0 (south wall), second half on y=hall_d (north wall),
    spaced uniformly along the x-axis.
    """
    crahs: List[dict] = []
    half = n // 2
    remainder = n - half * 2  # 0 or 1 extra goes to south wall

    south_count = half + remainder
    north_count = half

    for i in range(south_count):
        x = round(hall_w * (i + 1) / (south_count + 1), 3)
        crahs.append({
            "id": f"crah-{len(crahs) + 1}",
            "wall": "south",
            "pos": [x, 0.0, hall_h / 2.0],
        })

    for i in range(north_count):
        x = round(hall_w * (i + 1) / (north_count + 1), 3)
        crahs.append({
            "id": f"crah-{len(crahs) + 1}",
            "wall": "north",
            "pos": [x, hall_d, hall_h / 2.0],
        })

    return crahs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_hall_topology(
    building_json: str,
    dt_prototxt: str,
    hall: str = "1f 2a",
) -> dict:
    """Return a pure, deterministic topology dict for the given hall.

    Parameters
    ----------
    building_json : path to models/building.json (relative or absolute)
    dt_prototxt   : path to configs/dt/dt.prototxt (relative or absolute)
    hall          : hall identifier, e.g. "1f 2a"

    Returns
    -------
    dict with keys: hall, crahs, rack_rows, plant, links
    """
    # Hall schematic bounding box
    hall_size = [30.0, 20.0, 4.0]  # [width_x, depth_y, height_z] in metres
    hall_w, hall_d, hall_h = hall_size

    hall_name = f"Data Hall {hall.upper()}"

    # 1. CRAHs
    n_crahs = _count_crahs_from_prototxt(dt_prototxt, hall)
    crahs = _place_crahs(n_crahs, hall_w, hall_d, hall_h)

    # 2. Rack rows
    rack_rows = _rack_rows_from_room2ite(building_json, hall)

    # 3. Plant block — positioned outside the hall (x < 0 side)
    plant_counts = _read_plant_counts(building_json)
    plant_pos = [-8.0, hall_d / 2.0, 0.0]  # schematic offset

    # 4. CHW links: plant -> each CRAH
    links = [{"from": "plant", "to": c["id"]} for c in crahs]

    return {
        "hall": {
            "name": hall_name,
            "size": hall_size,
        },
        "crahs": crahs,
        "rack_rows": rack_rows,
        "plant": {
            **plant_counts,
            "pos": plant_pos,
        },
        "links": links,
    }
