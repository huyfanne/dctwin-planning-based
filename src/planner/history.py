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
    """Re-run the forecaster fit so the next plan sees the advanced history.

    P2 seam — not yet wired.  This function is a placeholder for the P2
    calibration/uncertainty/robust loop; it will be connected once the
    realized-history file (data/realized_history.csv) is large enough to
    support re-fitting.  Do not delete."""
    import runpy
    runpy.run_path("fit_forecaster.py", run_name="__main__")
