#!/usr/bin/env python
"""Recouple the 1F-2A ITE rack inlets to the controlled supply air (root-cause fix).

ROOT CAUSE (see docs/superpowers/specs/2026-06-08-setpoint-invariance-rootcause-design.md):
every `ELECTRICEQUIPMENT:ITE:AIRCOOLED` unit's *recirculation* curve is a hard constant 1.0,
so under EnergyPlus `AdjustedSupply`:

    T_inlet = RecircFrac * T_zone + (1 - RecircFrac) * T_supply

RecircFrac = 1.0 makes the `(1-RecircFrac)*T_supply` term vanish -> T_inlet = T_zone exactly,
so the CRAH supply-air-temp / airflow / CHWST setpoints have ZERO effect on the safety-binding
sensor (max ITE inlet). Every candidate is infeasible by the same margin (ITE-16 = 43.64 C,
bit-identical across all 125 search candidates) and the planner collapses to one fixed corner.

This script sets the 22 `data hall 1f 2a ite-N recirculation ...` BIQUADRATIC curves'
`Coefficient1 Constant` to RECIRC_FRACTION so the inlet tracks the cooled supply air and the
optimisation becomes well-posed (setpoints move the inlet; the <=26 C cap becomes reachable).

CALIBRATION ASSUMPTION (flagged for later): RECIRC_FRACTION = 0.10 models good hot/cold-aisle
containment (~90% of the inlet follows the cooled supply). This is a *reasonable default*, NOT
a measured value — recalibrate against measured rack-inlet data when available.

The model IDF is gitignored, so this tracked, idempotent script (with a one-time backup) is the
reviewable, reproducible record of the change. Re-running is safe; restore with --restore.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

RECIRC_FRACTION = 0.10
IDF = Path(__file__).resolve().parents[1] / "src" / "models" / "idf" / "building.idf"
BACKUP = IDF.with_name("building.idf.recirc_orig")
# only the controlled hall's ITE recirculation curves (22 units)
NAME_RE = re.compile(r"data hall 1f 2a ite-\d+ recirculation function", re.I)
EXPECTED = 22


def restore() -> None:
    if not BACKUP.exists():
        sys.exit("no backup (building.idf.recirc_orig) to restore from")
    shutil.copy(BACKUP, IDF)
    print(f"restored {IDF} from {BACKUP.name}")


def apply(fraction: float = RECIRC_FRACTION) -> int:
    if not BACKUP.exists():
        shutil.copy(IDF, BACKUP)          # one-time backup of the original
    lines = IDF.read_text().splitlines(keepends=True)
    n = 0
    for i, ln in enumerate(lines):
        if NAME_RE.search(ln) and "!- Name" in ln:
            j = i + 1                     # the next field is 'Coefficient1 Constant'
            lines[j] = re.sub(r"^(\s*)[-0-9.]+(\s*,)", rf"\g<1>{fraction}\g<2>", lines[j])
            n += 1
    IDF.write_text("".join(lines))
    print(f"recoupled {n} 1F-2A ITE recirculation curves -> Coefficient1 Constant = {fraction}")
    if n != EXPECTED:
        sys.exit(f"expected {EXPECTED} 1F-2A curves, patched {n} — aborting (check the IDF)")
    return n


if __name__ == "__main__":
    if "--restore" in sys.argv:
        restore()
    else:
        apply()
