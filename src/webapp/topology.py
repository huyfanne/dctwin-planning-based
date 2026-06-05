"""topology.py — pure, deterministic topology builder for the GDS model.

Reads the GDS assets to derive both:
  - the full BUILDING: every data hall / room as a real box (from the IDF zone
    geometry — World coordinates), stacked at its true z-level, with its level,
    ITE count and which one is operator-controlled; and
  - the controlled hall's DETAIL: 22 AGENT_CONTROLLED ACUs (1F 2A) along two
    walls, rack rows down the middle, plant block, and CHW links.

No dctwin imports; no side effects.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# IDF geometry — real per-zone bounding boxes (World coordinate system)
# ---------------------------------------------------------------------------

_HALL_KEYWORDS = ("hall", "core", "room")
# BuildingSurface:Detailed field order (EP 9.5): 0 Name, 1 Type, 2 Construction,
# 3 Zone Name, 4 OBC, 5 OBC Object, 6 Sun, 7 Wind, 8 ViewFactor, 9 #Vertices,
# 10.. vertices (x,y,z triples).
_VERTEX_START = 10


def parse_zone_bboxes(idf_path: str) -> Dict[str, Tuple[float, float, float, float, float, float]]:
    """Return {zone_name_lower: (minx,maxx,miny,maxy,minz,maxz)} from the IDF.

    Aggregates the vertices of every BuildingSurface:Detailed by its zone.
    Assumes GlobalGeometryRules World coordinates (absolute), which the GDS IDF uses.
    """
    text = re.sub(r"!.*", "", Path(idf_path).read_text())  # strip comments
    boxes: Dict[str, list] = {}
    for m in re.finditer(r"(?is)BuildingSurface:Detailed\s*,(.*?);", text):
        toks = [t.strip() for t in m.group(1).split(",")]
        if len(toks) <= _VERTEX_START:
            continue
        zone = toks[3].lower()
        coords: List[float] = []
        for t in toks[_VERTEX_START:]:
            try:
                coords.append(float(t))
            except ValueError:
                pass
        bb = boxes.setdefault(zone, [1e9, -1e9, 1e9, -1e9, 1e9, -1e9])
        for i in range(0, len(coords) - 2, 3):
            x, y, z = coords[i], coords[i + 1], coords[i + 2]
            bb[0] = min(bb[0], x); bb[1] = max(bb[1], x)
            bb[2] = min(bb[2], y); bb[3] = max(bb[3], y)
            bb[4] = min(bb[4], z); bb[5] = max(bb[5], z)
    return {z: tuple(bb) for z, bb in boxes.items()}


def _hall_label(zone_name: str) -> Tuple[str, str]:
    """('data hall 1f 2a') -> (code 'Data Hall 1F 2A', level '1F')."""
    # Title-case but keep floor tokens (GF/1F/2F) upper.
    parts = zone_name.split()
    pretty = " ".join(
        p.upper() if re.fullmatch(r"(?i)(gf|\d+f|\d+[ab])", p) else p.capitalize()
        for p in parts
    )
    level_tok = next((p.upper() for p in parts if re.fullmatch(r"(?i)gf|\d+f", p)), "—")
    return pretty, level_tok


def _ite_counts(room2ite_path: Path) -> Dict[str, int]:
    if not room2ite_path.exists():
        return {}
    r2i = json.loads(room2ite_path.read_text())
    return {k.lower(): len(v) for k, v in r2i.items()}


def build_building_topology(idf_path: str, room2ite_path: Path,
                            controlled_hall: str = "1f 2a") -> dict:
    """All data halls / rooms as stacked real boxes, plus building extents."""
    boxes = parse_zone_bboxes(idf_path)
    ites = _ite_counts(room2ite_path)
    ctrl_canon = f"data hall {controlled_hall.lower()}"

    halls: List[dict] = []
    fp_w = fp_d = top = 0.0
    for zone, bb in boxes.items():
        if not any(k in zone for k in _HALL_KEYWORDS):
            continue
        minx, maxx, miny, maxy, minz, maxz = bb
        w, d, h = maxx - minx, maxy - miny, maxz - minz
        name, level = _hall_label(zone)
        halls.append({
            "code": name,
            "level": level,
            "origin": [round(minx, 2), round(miny, 2), round(minz, 2)],
            "size": [round(w, 2), round(d, 2), round(h, 2)],
            "z0": round(minz, 2),
            "controlled": zone == ctrl_canon,
            "ite": ites.get(zone, 0),
        })
        fp_w = max(fp_w, maxx); fp_d = max(fp_d, maxy); top = max(top, maxz)

    halls.sort(key=lambda hh: hh["z0"])  # ground -> top
    return {
        "footprint": [round(fp_w, 2), round(fp_d, 2)],
        "height": round(top, 2),
        "halls": halls,
    }


# ---------------------------------------------------------------------------
# Controlled-hall detail (CRAHs / racks / plant / links)
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


def _rack_rows(n_ite: int, hall_w: float, hall_d: float) -> List[dict]:
    """Deterministic 6 rows of racks down the middle of the hall (alternating aisles)."""
    n_rows = 6
    nracks_per_row = max(1, (n_ite // n_rows) if n_ite >= n_rows else 10)
    # rows run along x; placed in the middle half of the depth (y), centred.
    band = hall_d * 0.5
    y_start = (hall_d - band) / 2.0
    row_spacing = band / max(n_rows - 1, 1)
    rows: List[dict] = []
    for i in range(n_rows):
        rows.append({
            "id": f"row-{i + 1}",
            "aisle": "cold" if i % 2 == 0 else "hot",
            "nracks": nracks_per_row,
            "pos": [hall_w / 2.0, round(y_start + i * row_spacing, 3), 0.0],
        })
    return rows


def _place_crahs(n: int, hall_w: float, hall_d: float, hall_h: float) -> List[dict]:
    """Place n CRAHs along the two long walls (y=0 and y=hall_d), spaced along x."""
    crahs: List[dict] = []
    half = n // 2
    south_count = half + (n - half * 2)
    north_count = half
    for i in range(south_count):
        crahs.append({"id": f"crah-{len(crahs) + 1}", "wall": "south",
                      "pos": [round(hall_w * (i + 1) / (south_count + 1), 3), 0.0, hall_h / 2.0]})
    for i in range(north_count):
        crahs.append({"id": f"crah-{len(crahs) + 1}", "wall": "north",
                      "pos": [round(hall_w * (i + 1) / (north_count + 1), 3), hall_d, hall_h / 2.0]})
    return crahs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_hall_topology(
    building_json: str,
    dt_prototxt: str,
    hall: str = "1f 2a",
    idf_path: str | None = None,
) -> dict:
    """Topology for the 3D view: the controlled hall's detail + the whole building.

    Returns a dict with: hall, crahs, rack_rows, plant, links, building.
    `idf_path` defaults to <building_json dir>/idf/building.idf.
    """
    bjson = Path(building_json)
    if idf_path is None:
        idf_path = str(bjson.parent / "idf" / "building.idf")
    room2ite_path = bjson.parent.parent / "configs" / "dt" / "room2ite_map.json"

    # 1. Whole building (all halls/levels), with real geometry.
    building = build_building_topology(idf_path, room2ite_path, controlled_hall=hall)

    # 2. Controlled hall real size (fallback to a schematic box if not found).
    ctrl = next((h for h in building["halls"] if h["controlled"]), None)
    hall_size = ctrl["size"] if ctrl else [42.46, 22.55, 3.5]
    hall_w, hall_d, hall_h = hall_size
    hall_name = ctrl["code"] if ctrl else f"Data Hall {hall.upper()}"
    n_ite = ctrl["ite"] if ctrl else 0

    # 3. Detail: CRAHs (from the prototxt), rack rows, plant, CHW links.
    n_crahs = _count_crahs_from_prototxt(dt_prototxt, hall)
    crahs = _place_crahs(n_crahs, hall_w, hall_d, hall_h)
    rack_rows = _rack_rows(n_ite, hall_w, hall_d)
    plant_counts = _read_plant_counts(building_json)
    links = [{"from": "plant", "to": c["id"]} for c in crahs]

    return {
        "hall": {"name": hall_name, "size": hall_size},
        "crahs": crahs,
        "rack_rows": rack_rows,
        "plant": {**plant_counts, "pos": [-8.0, hall_d / 2.0, 0.0]},
        "links": links,
        "building": building,
    }
