"""Advance the forecaster's realized-history with each deployed week (loop closure).

In sim+perturbed-plant this extends the rolling history the persistence/seasonal
forecaster reads; the *fidelity* learning (calibration) is added in P2a."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def advance_history(realized: dict, week_start: date, his_csv: str) -> None:
    """Append (or replace) the realized-week summary row keyed by week_start."""
    path = Path(his_csv)
    df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    row = {"week_start": week_start.isoformat(), **realized}
    if "week_start" in df.columns:
        df = df[df["week_start"] != week_start.isoformat()]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False)


def refit_from_history(forecaster_pkl: str = "models/forecaster.pkl") -> None:
    """Re-run the forecaster fit so the next plan sees the advanced history."""
    import runpy
    runpy.run_path("fit_forecaster.py", run_name="__main__")
