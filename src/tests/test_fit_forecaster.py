import pickle
from pathlib import Path

from fit_forecaster import build_his_col_for_room, save_forecaster_config


def test_build_his_col_for_room_matches_columns():
    cols = [
        "_time",
        "1F_Datahall 2A 1F Data Hall 2A IT loads",
        "GF_Datahall 1A GF Data Hall 1A IT loads",
    ]
    room2ite = {
        "Data Hall 1F 2A": {"Data Hall 1F 2A ite-1": {"totalWatts": 1.0}},
        "Data Hall GF 1A": {"Data Hall GF 1A ite-1": {"totalWatts": 1.0}},
        "Super Core Room 1F": {"x": {"totalWatts": 1.0}},
    }
    mapping = build_his_col_for_room(room2ite, cols)
    assert mapping["Data Hall 1F 2A"] == "1F_Datahall 2A 1F Data Hall 2A IT loads"
    assert mapping["Data Hall GF 1A"] == "GF_Datahall 1A GF Data Hall 1A IT loads"
    assert "Super Core Room 1F" not in mapping


def test_save_forecaster_config_roundtrip(tmp_path):
    cfg = {"method": "persistence", "his_col_for_room": {"a": "b"}}
    out = tmp_path / "forecaster.pkl"
    save_forecaster_config(cfg, str(out))
    assert pickle.loads(out.read_bytes()) == cfg
