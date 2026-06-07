"""Advance the realized-KPI history with each deployed week (loop closure).

This module accumulates a SEPARATE realized-KPI history file (one row per
deployed week, consumed later by P2 calibration).  It must NOT be pointed at
the forecaster's per-step IT-load CSV (data/his_data_processed.csv), which has
a completely different schema (15-min, 384 columns); appending a weekly KPI row
there would corrupt it with NaN columns and poison future forecasts."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def advance_history(realized: dict, week_start: date, his_csv: str) -> None:
    """Append (or replace) the realized-week summary row keyed by week_start.

    ``his_csv`` must point to a SEPARATE realized-KPI history file (e.g.
    ``data/realized_history.csv``), NOT to the forecaster's per-step IT-load
    CSV.  Each row has ``week_start`` plus whatever keys are in ``realized``
    (e.g. total_hvac_energy_kwh, pue_mean, inlet_temp_max_c, …)."""
    path = Path(his_csv)
    df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    row = {"week_start": week_start.isoformat(), **realized}
    if "week_start" in df.columns:
        df = df[df["week_start"] != week_start.isoformat()]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False)


def refit_from_history(forecaster_pkl: str = "models/forecaster.pkl") -> None:
    """Documented NO-OP seam (sim-only v1).

    In sim-only mode the realized IT-load EQUALS the forecast we injected (the
    perturbed plant degrades cooling, not load), and the realized record is
    aggregate weekly KPIs — schema-incompatible with the forecaster's per-step
    IT-load CSV. So there is no forecaster feedback to apply: the realized-feedback
    path is the CALIBRATION loop (advance_calibration -> recompute_calibration ->
    corrected objective). This seam activates only with real per-step telemetry
    (parked with the BMS/telemetry work). Mirrors planner.recalibrator.recalibrate.
    Do not delete."""
    return None


def advance_calibration(predicted: dict, realized: dict, week_start: date,
                        path: str = "data/calibration_history.json") -> None:
    """Append/replace one paired (predicted, realized) KPI record per deployed week.

    This is the SEPARATE paired history the P2 Calibrator fits residuals from — NOT
    the forecaster's per-step CSV. Idempotent per week_start."""
    import json
    p = Path(path)
    hist = json.loads(p.read_text()) if p.exists() else []
    hist = [e for e in hist if e.get("week_start") != week_start.isoformat()]
    hist.append({"week_start": week_start.isoformat(),
                 "predicted": predicted, "realized": realized})
    hist.sort(key=lambda e: e["week_start"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hist, indent=2))
