#!/usr/bin/env python
r"""recirc sensitivity sweep — how the uncalibrated recirculation fraction moves the
binding inlet temperature and the (hall-scoped) HVAC energy.

WHY: recouple_ite_recirc.py sets RECIRC_FRACTION = 0.10 as a *reasonable default* (good
hot/cold-aisle containment), NOT a measured value. There is no measured per-rack inlet
data to calibrate it (his_data is power/PDU telemetry only). This sweep quantifies the
uncertainty: it re-runs ONE fixed mid-range setpoint at recirc in {0.05, 0.10, 0.15, 0.20}
and reports inlet_temp_max + energy, so we know how sensitive the safety margin / setpoint
choice is to the assumption.

REAL EnergyPlus — run manually with Docker (slow); NOT part of the unit suite:

    sg docker -c "env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src PYTHONPATH=\$PWD \
        /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python \
        ../scripts/recirc_sensitivity.py --week 2024-11-11 --days 3"

It restores the IDF to the 0.10 default on exit (even on error), so it never leaves the
model in a swept state.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import recouple_ite_recirc as recouple  # noqa: E402  (apply/restore the curve constant)

RECIRC_GRID = (0.05, 0.10, 0.15, 0.20)
DEFAULT_RECIRC = 0.10
OUT_MD = ROOT / "docs" / "superpowers" / "specs" / "2026-06-08-recirc-sensitivity.md"


def _build_forecast(week_start: date, n_steps: int):
    import pandas as pd
    from planner.forecaster import build_forecaster

    cfg = pickle.load(open(ROOT / "src" / "models" / "forecaster.pkl", "rb"))
    his = pd.read_csv(ROOT / "src" / cfg["his_csv"])
    room2ite = json.loads((ROOT / "src" / cfg["room2ite_path"]).read_text())
    fc = build_forecaster(cfg["method"], his, room2ite, cfg["his_col_for_room"],
                          weather_file=cfg.get("weather_file"))
    return fc.forecast(week_start, n_steps)


def run(week_start: date, days: int, n_workers: int) -> list[dict]:
    from planner.oracle import OracleConfig, ParallelEnvOracle
    from planner.types import DEFAULT_SEARCH_SPACE, Setpoints

    space = DEFAULT_SEARCH_SPACE
    tph = 4
    n_steps = days * 24 * tph
    forecast = _build_forecast(week_start, n_steps)
    # a fixed, interior setpoint so only recirc varies between rows
    mid = Setpoints((space.sat.lb + space.sat.ub) / 2,
                    (space.flow.lb + space.flow.ub) / 2,
                    (space.chwst.lb + space.chwst.ub) / 2)

    oracle = ParallelEnvOracle(
        base_prototxt="configs/dt/dt.prototxt", project_root=".",
        config=OracleConfig(n_workers=n_workers, timesteps_per_hour=tph,
                            log_root=str(ROOT / "src" / "runs" / "_recirc_sweep")),
    )
    rows = []
    for recirc in RECIRC_GRID:
        recouple.apply(recirc)
        kpi = oracle.evaluate([mid], forecast)[0]
        rows.append({"recirc": recirc,
                     "inlet_temp_max_c": round(kpi.inlet_temp_max, 3),
                     "inlet_violation_steps": kpi.inlet_violation_steps,
                     "hvac_energy_kwh": round(kpi.total_hvac_energy_kwh, 1),
                     "feasible": bool(kpi.feasible and kpi.inlet_violation_steps == 0)})
        print(f"recirc={recirc:.2f}  inlet_max={kpi.inlet_temp_max:.2f}C  "
              f"viol={kpi.inlet_violation_steps}  energy={kpi.total_hvac_energy_kwh:.0f}kWh")
    return rows


def write_md(rows: list[dict], week_start: date, days: int) -> None:
    lines = [
        "# recirc Sensitivity Sweep — Results", "",
        f"Fixed mid-range setpoint; week_start={week_start.isoformat()}, days={days}. "
        "Energy is the hall-scoped controllable HVAC (1F-2A fans + chiller/CHW plant).", "",
        "| recirc | inlet max (°C) | inlet violations | HVAC energy (kWh) | feasible |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['recirc']:.2f} | {r['inlet_temp_max_c']} | "
                     f"{r['inlet_violation_steps']} | {r['hvac_energy_kwh']} | {r['feasible']} |")
    lines += ["", "Higher recirc -> more hot-air recirculation -> hotter inlet (less safety "
              "margin). The 0.10 default assumes good containment; recalibrate against measured "
              "rack-inlet temps when available (see the monitor-safety review)."]
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT_MD}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="2024-11-11")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    ws = date.fromisoformat(args.week)
    try:
        rows = run(ws, args.days, args.workers)
        write_md(rows, ws, args.days)
    finally:
        recouple.apply(DEFAULT_RECIRC)   # always restore the shipped default
        print(f"restored recirc -> {DEFAULT_RECIRC}")


if __name__ == "__main__":
    main()
