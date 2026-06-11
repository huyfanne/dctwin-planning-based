"""Fit the live recirculation fraction r0 from telemetry and write data/recirc.json.

Sources (mutually exclusive):
  --db   the webapp telemetry sqlite (table telemetry(ts, point, value)): rack inlets are
         the `rack_inlet_c/<rack>` points, supply is `held/sat_c`; the return temp is a
         historian point (--return-point) or, when no return sensor exists (the sim feed),
         a constant (--return-c). Samples are joined on their shared snapshot ts.
  --csv  columns inlet_c,supply_c[,return_c] (return_c optional with --return-c).

`--write` updates data/recirc.json with the fitted r0 only — demand_kg_s (the CRAH-vs-ITE
airflow calibration) and k are deliberately preserved (None/absent -> defaults), so an r
fit can never silently engage the flow-shortfall penalty.

Example:
    env -C .../src .../.venv-dtwin/bin/python fit_recirc.py \
        --db runs/telemetry.sqlite --return-c 32.0 --write
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Optional

from planner.recirc import DEFAULT_RECIRC_CONFIG, RECIRC_CONFIG_PATH, estimate_recirc_fraction


def rows_from_sqlite(db_path: str, supply_point: str = "held/sat_c",
                     inlet_prefix: str = "rack_inlet_c/",
                     return_point: Optional[str] = None,
                     return_c: Optional[float] = None) -> list[tuple]:
    """(inlet, supply, return, rack) tuples joined on the shared per-snapshot ts (the sim
    feed and snapshot-style collectors write every point of a tick with one ts).
    Snapshots missing the supply or return temperature are skipped, never guessed."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("SELECT ts, point, value FROM telemetry ORDER BY ts")
        snapshots: dict[float, dict[str, float]] = {}
        for ts, point, value in cur:
            snapshots.setdefault(ts, {})[point] = value
    finally:
        con.close()
    rows: list[tuple] = []
    for points in snapshots.values():
        supply = points.get(supply_point)
        if supply is None:
            continue
        ret = points.get(return_point) if return_point else None
        if ret is None:
            ret = return_c
        if ret is None:
            continue
        for name, value in points.items():
            if name.startswith(inlet_prefix):
                rows.append((value, supply, ret, name[len(inlet_prefix):]))
    return rows


def rows_from_csv(csv_path: str, return_c: Optional[float] = None) -> list[tuple]:
    """(inlet, supply, return) tuples from inlet_c,supply_c[,return_c] columns;
    a missing/empty return_c cell falls back to the --return-c constant."""
    rows: list[tuple] = []
    with open(csv_path, newline="") as f:
        for rec in csv.DictReader(f):
            raw_ret = rec.get("return_c")
            ret = float(raw_ret) if raw_ret not in (None, "") else return_c
            if ret is None:
                continue
            rows.append((float(rec["inlet_c"]), float(rec["supply_c"]), ret))
    return rows


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(
        description="Fit the recirculation fraction r0 from rack-inlet telemetry")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--db", help="telemetry sqlite: table telemetry(ts, point, value)")
    src.add_argument("--csv", help="CSV with columns inlet_c,supply_c[,return_c]")
    ap.add_argument("--supply-point", default="held/sat_c",
                    help="held supply-air temperature point name (sqlite)")
    ap.add_argument("--inlet-prefix", default="rack_inlet_c/",
                    help="rack-inlet point-name prefix (sqlite)")
    ap.add_argument("--return-point", default=None,
                    help="historian return/zone-temp point name (sqlite)")
    ap.add_argument("--return-c", type=float, default=None,
                    help="constant return temp (deg C) when no return sensor exists")
    ap.add_argument("--out", default=RECIRC_CONFIG_PATH)
    ap.add_argument("--write", action="store_true",
                    help="write the fitted r0 to --out (demand_kg_s/k preserved)")
    args = ap.parse_args(argv)

    if args.db:
        rows = rows_from_sqlite(args.db, supply_point=args.supply_point,
                                inlet_prefix=args.inlet_prefix,
                                return_point=args.return_point, return_c=args.return_c)
    else:
        rows = rows_from_csv(args.csv, return_c=args.return_c)

    est = estimate_recirc_fraction(rows)
    if est["n"] == 0:
        raise SystemExit("fit_recirc: no usable telemetry rows "
                         "(need supply+return temps with |Tret - Tsup| >= 1 C)")
    racks = f" across {len(est['r_per_rack'])} racks" if est["r_per_rack"] else ""
    print(f"fitted r = {est['r']:.4f} from n = {est['n']} samples{racks}")

    if args.write:
        out = Path(args.out)
        existing = json.loads(out.read_text()) if out.exists() else {}
        cfg = {
            "r0": round(est["r"], 4),
            # demand_kg_s is a separate calibration (CRAH vs ITE airflow); never invent it here
            "demand_kg_s": existing.get("demand_kg_s") or DEFAULT_RECIRC_CONFIG["demand_kg_s"],
            "k": existing.get("k") or DEFAULT_RECIRC_CONFIG["k"],
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cfg, indent=2) + "\n")
        print(f"wrote {out}")
    return est


if __name__ == "__main__":
    main()
