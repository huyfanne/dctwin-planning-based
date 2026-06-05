"""topology.py — pure, deterministic topology builder for the GDS model.

Reads the GDS assets to derive both:
  - the full BUILDING: every data hall / room as a real box (from the IDF zone
    geometry — World coordinates), stacked at its true z-level, each carrying its
    verified infrastructure (ACU count from the IDF air loops, agent-controlled
    ACU count from the prototxt, ITE objects/units + IT power from room2ite) and
    its own equipment layout (ACUs + rack rows); and
  - the controlled hall's DETAIL (1F 2A): 22 AGENT_CONTROLLED ACUs, rack rows,
    plant block, and CHW links (kept at the top level for back-compat).

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


def _bboxes_from_text(text: str) -> Dict[str, Tuple[float, float, float, float, float, float]]:
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


def parse_zone_bboxes(idf_path: str) -> Dict[str, Tuple[float, float, float, float, float, float]]:
    """Return {zone_name_lower: (minx,maxx,miny,maxy,minz,maxz)} from the IDF.

    Aggregates the vertices of every BuildingSurface:Detailed by its zone.
    Assumes GlobalGeometryRules World coordinates (absolute), which the GDS IDF uses.
    """
    return _bboxes_from_text(re.sub(r"!.*", "", Path(idf_path).read_text()))


def _acu_counts_from_text(idf_text: str, zones: List[str]) -> Dict[str, int]:
    """Per-zone ACU/air-loop count: distinct '<zone> acu-N' identifiers in the IDF."""
    low = idf_text.lower()
    return {z: len(set(re.findall(re.escape(z) + r" acu-(\d+)", low))) for z in zones}


def _hall_label(zone_name: str) -> Tuple[str, str]:
    """('data hall 1f 2a') -> (code 'Data Hall 1F 2A', level '1F')."""
    parts = zone_name.split()
    pretty = " ".join(
        p.upper() if re.fullmatch(r"(?i)(gf|\d+f|\d+[ab])", p) else p.capitalize()
        for p in parts
    )
    level_tok = next((p.upper() for p in parts if re.fullmatch(r"(?i)gf|\d+f", p)), "—")
    return pretty, level_tok


def _ite_detail(room2ite_path: Path) -> Dict[str, dict]:
    """Per-room ITE: {zone_lower: {objects, units, powerKw}} from room2ite_map.json.

    room2ite maps room -> {ite_name: {wattsPerUnit, numberOfUnits, totalWatts}}.
    """
    if not room2ite_path.exists():
        return {}
    r2i = json.loads(room2ite_path.read_text())
    out: Dict[str, dict] = {}
    for room, items in r2i.items():
        vals = list(items.values()) if isinstance(items, dict) else []
        out[room.lower()] = {
            "objects": len(items) if isinstance(items, dict) else 0,
            "units": sum(int(v.get("numberOfUnits", 0)) for v in vals),
            "powerKw": round(sum(float(v.get("totalWatts", 0.0)) for v in vals) / 1000.0, 1),
        }
    return out


def _count_controlled_acus(prototxt_path: str, hall: str) -> int:
    """Count AGENT_CONTROLLED ACU supply-air-temperature-setpoint actions for `hall`."""
    hall_slug = hall.lower().replace(" ", "_")
    pattern = re.compile(
        r'variable_name\s*:\s*"data_hall_'
        + re.escape(hall_slug)
        + r'_acu_\d+_supply_air_temperature_setpoint"'
    )
    return len(pattern.findall(Path(prototxt_path).read_text()))


# ---------------------------------------------------------------------------
# Per-hall equipment layout (deterministic, schematic within the real box)
# ---------------------------------------------------------------------------

def _rack_rows(hall_w: float, hall_d: float, n_rows: int = 6, per_row: int = 8) -> List[dict]:
    """A representative rack field down the middle of the hall (alternating aisles)."""
    band = hall_d * 0.5
    y_start = (hall_d - band) / 2.0
    row_spacing = band / max(n_rows - 1, 1)
    rows: List[dict] = []
    for i in range(n_rows):
        rows.append({
            "id": f"row-{i + 1}",
            "aisle": "cold" if i % 2 == 0 else "hot",
            "nracks": per_row,
            "pos": [hall_w / 2.0, round(y_start + i * row_spacing, 3), 0.0],
        })
    return rows


def _place_crahs(n: int, hall_w: float, hall_d: float, hall_h: float) -> List[dict]:
    """Place n ACUs/CRAHs along the two long walls (y=0 and y=hall_d), spaced along x."""
    crahs: List[dict] = []
    if n <= 0:
        return crahs
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


def _read_plant_counts(building_json: str) -> dict:
    """Read chiller / coolingTower / pump counts from building.json coolingModels."""
    data = json.loads(Path(building_json).read_text())
    cm = data["models"]["coolingModels"]
    return {
        "chiller": len(cm.get("chillers", {})),
        "coolingTower": len(cm.get("coolingTowers", {})),
        "pumps": len(cm.get("pumps", {})),
    }


# ---------------------------------------------------------------------------
# Building topology — every hall with verified infrastructure + equipment
# ---------------------------------------------------------------------------

def build_building_topology(idf_path: str, room2ite_path: Path, dt_prototxt: str,
                            controlled_hall: str = "1f 2a") -> dict:
    """All data halls / rooms as stacked real boxes, each with its verified
    infrastructure (ACUs, agent-controlled ACUs, ITE objects/units, IT power) and
    its own equipment layout, plus the building extents."""
    idf_text = re.sub(r"!.*", "", Path(idf_path).read_text())
    boxes = _bboxes_from_text(idf_text)
    ites = _ite_detail(room2ite_path)
    zone_names = [z for z in boxes if any(k in z for k in _HALL_KEYWORDS)]
    acus = _acu_counts_from_text(idf_text, zone_names)
    ctrl_canon = f"data hall {controlled_hall.lower()}"

    halls: List[dict] = []
    fp_w = fp_d = top = 0.0
    for zone in zone_names:
        minx, maxx, miny, maxy, minz, maxz = boxes[zone]
        w, d, h = maxx - minx, maxy - miny, maxz - minz
        name, level = _hall_label(zone)
        controlled = zone == ctrl_canon
        ite = ites.get(zone, {"objects": 0, "units": 0, "powerKw": 0.0})
        acu_total = acus.get(zone, 0)
        short = zone.replace("data hall ", "").strip()
        acu_controlled = _count_controlled_acus(dt_prototxt, short)
        hvac = (
            f"{acu_total} ACU{'s' if acu_total != 1 else ''} · "
            f"{'agent-controlled SAT + airflow' if acu_controlled else 'scheduled SAT 23°C'} · "
            "water-cooled VAV"
        )
        halls.append({
            "code": name,
            "level": level,
            "origin": [round(minx, 2), round(miny, 2), round(minz, 2)],
            "size": [round(w, 2), round(d, 2), round(h, 2)],
            "z0": round(minz, 2),
            "controlled": controlled,
            "ite": ite["objects"],                 # back-compat (ITE object count)
            "infra": {
                "acuTotal": acu_total,
                "acuControlled": acu_controlled,
                "iteObjects": ite["objects"],
                "iteUnits": ite["units"],
                "itPowerKw": ite["powerKw"],
                "hvac": hvac,
            },
            "crahs": _place_crahs(acu_total, w, d, h),
            "rackRows": _rack_rows(w, d),
        })
        fp_w = max(fp_w, maxx); fp_d = max(fp_d, maxy); top = max(top, maxz)

    halls.sort(key=lambda hh: hh["z0"])  # ground -> top
    return {
        "footprint": [round(fp_w, 2), round(fp_d, 2)],
        "height": round(top, 2),
        "halls": halls,
    }


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

    # 1. Whole building (all halls/levels) with verified infra + per-hall equipment.
    building = build_building_topology(idf_path, room2ite_path, dt_prototxt, controlled_hall=hall)
    plant_counts = _read_plant_counts(building_json)
    building["plant"] = plant_counts

    # 2. Controlled hall -> top-level detail (back-compat for the airflow + tests).
    ctrl = next((h for h in building["halls"] if h["controlled"]), None)
    if ctrl is not None:
        hall_size = ctrl["size"]
        hall_name = ctrl["code"]
        crahs = ctrl["crahs"]
        rack_rows = ctrl["rackRows"]
    else:  # assets missing the controlled hall -> schematic fallback
        hall_size = [42.46, 22.55, 3.5]
        hall_name = f"Data Hall {hall.upper()}"
        crahs = _place_crahs(_count_controlled_acus(dt_prototxt, hall), *hall_size)
        rack_rows = _rack_rows(hall_size[0], hall_size[1])

    links = [{"from": "plant", "to": c["id"]} for c in crahs]
    return {
        "hall": {"name": hall_name, "size": hall_size},
        "crahs": crahs,
        "rack_rows": rack_rows,
        "plant": {**plant_counts, "pos": [-8.0, hall_size[1] / 2.0, 0.0]},
        "links": links,
        "building": building,
    }
