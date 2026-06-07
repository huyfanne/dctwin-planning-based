"""Write a pre-validation per-step trajectory to CSV (the diagram's trajectory_*.csv)."""
from __future__ import annotations

from pathlib import Path

_COLS = ("step", "inlet_temp_max_c", "hvac_power_kw", "pue")


def write_trajectory_csv(rows: list[dict], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(_COLS)]
    for r in rows:
        lines.append(",".join("" if r.get(c) is None else str(r.get(c)) for c in _COLS))
    Path(path).write_text("\n".join(lines) + "\n")
