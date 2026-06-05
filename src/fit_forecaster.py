from __future__ import annotations

import json
import logging
import pickle
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _room_token(room: str) -> str:
    """'Data Hall 1F 2A' -> tokens '1f 2a' for fuzzy column matching."""
    return room.lower().replace("data hall", "").strip()


def build_his_col_for_room(room2ite: dict, columns: list[str]) -> dict[str, str]:
    """Map each room to its 'IT loads' column in his_data by fuzzy name match."""
    it_cols = [c for c in columns if c.strip().lower().endswith("it loads")]
    mapping: dict[str, str] = {}
    for room in room2ite:
        token = _room_token(room)
        parts = [p for p in re.split(r"\s+", token) if p]
        for c in it_cols:
            cl = c.lower()
            if all(re.search(rf"\b{re.escape(p)}\b", cl) for p in parts):
                mapping[room] = c
                break
    for room in room2ite:
        if room not in mapping:
            logger.warning("fit_forecaster: no 'IT loads' column matched room %r", room)
    return mapping


def save_forecaster_config(config: dict, out_path: str) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(pickle.dumps(config))


def main(his_csv: str = "data/his_data_processed.csv",
         room2ite_path: str = "configs/dt/room2ite_map.json",
         method: str = "persistence",
         out_path: str = "models/forecaster.pkl") -> None:
    columns = pd.read_csv(his_csv, nrows=0).columns.tolist()
    room2ite = json.loads(Path(room2ite_path).read_text())
    his_col_for_room = build_his_col_for_room(room2ite, columns)
    config = {
        "method": method,
        "his_csv": his_csv,
        "room2ite_path": room2ite_path,
        "his_col_for_room": his_col_for_room,
    }
    save_forecaster_config(config, out_path)
    print(f"Fitted forecaster config -> {out_path}: {len(his_col_for_room)} rooms mapped")


if __name__ == "__main__":
    main()
