from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _atomic_write_json(path: Path, obj: Any, **dumps_kwargs) -> None:
    """Write JSON so a concurrent reader never sees a partial file: write a sibling
    temp file, then os.replace it into place (atomic on POSIX). Without this, a reader
    (e.g. the SSE progress poll) can catch the file truncated mid-write."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, **dumps_kwargs))
    os.replace(tmp, path)


def _read_json(path: Path, default):
    """Read JSON tolerantly: a missing, empty, or caught-mid-write file -> default."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):   # ValueError covers JSONDecodeError
        return default


class PlanStore:
    """Per-plan artifacts in runs/<id>/ + a SQLite index for history/list views."""

    def __init__(self, runs_dir: str = "runs", db_path: str = "runs/index.db"):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    week_start TEXT,
                    status TEXT,
                    params TEXT,
                    created_at TEXT,
                    energy_kwh REAL,
                    reduction_pct REAL
                )"""
            )
            # additive migration: realized energy for the History trend
            try:
                c.execute("ALTER TABLE plans ADD COLUMN realized_energy_kwh REAL")
            except sqlite3.OperationalError:
                pass  # column already exists

    def plan_dir(self, plan_id: str) -> Path:
        d = self.runs_dir / plan_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_plan(self, plan_id: str, week_start: str, params: dict) -> None:
        self.plan_dir(plan_id)
        with self._conn() as c:
            c.execute(
                "INSERT INTO plans (plan_id, week_start, status, params, created_at) "
                "VALUES (?, ?, 'queued', ?, ?)",
                (plan_id, week_start, json.dumps(params),
                 datetime.now(timezone.utc).isoformat()),
            )

    def set_status(self, plan_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE plans SET status=? WHERE plan_id=?", (status, plan_id))

    def save_recommendation(self, plan_id: str, rec: dict) -> None:
        _atomic_write_json(self.plan_dir(plan_id) / "recommendation.json", rec, indent=2)
        kpis = rec.get("predicted_kpis") or {}
        with self._conn() as c:
            c.execute(
                "UPDATE plans SET status=?, energy_kwh=?, reduction_pct=? WHERE plan_id=?",
                (rec.get("status"), kpis.get("total_hvac_energy_kwh"),
                 kpis.get("energy_reduction_vs_baseline_pct"), plan_id),
            )

    def get_recommendation(self, plan_id: str) -> Optional[dict]:
        return _read_json(self.plan_dir(plan_id) / "recommendation.json", None)

    def save_realized(self, plan_id: str, realized: dict) -> None:
        _atomic_write_json(self.plan_dir(plan_id) / "realized.json", realized, indent=2)
        with self._conn() as c:
            c.execute("UPDATE plans SET realized_energy_kwh=? WHERE plan_id=?",
                      (realized.get("total_hvac_energy_kwh"), plan_id))

    def get_realized(self, plan_id: str) -> Optional[dict]:
        return _read_json(self.plan_dir(plan_id) / "realized.json", None)

    def write_progress(self, plan_id: str, progress: dict) -> None:
        # Non-finite floats (e.g. best_score = +inf when all candidates are
        # infeasible) are invalid JSON and break the API response; store as null.
        safe = {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in progress.items()}
        _atomic_write_json(self.plan_dir(plan_id) / "progress.json", safe)

    def read_progress(self, plan_id: str) -> dict:
        data = _read_json(self.plan_dir(plan_id) / "progress.json", {})
        # defensively scrub any non-finite values from older files
        return {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in data.items()}

    def list_plans(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM plans ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_row(self, plan_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        return dict(r) if r else None

    def _read_traj_csv(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open() as f:
            for r in csv.DictReader(f):
                rows.append({
                    "step": int(r["step"]),
                    "inlet_temp_max_c": None if r["inlet_temp_max_c"] == "" else float(r["inlet_temp_max_c"]),
                    "hvac_power_kw": None if r["hvac_power_kw"] == "" else float(r["hvac_power_kw"]),
                    "pue": None if r["pue"] == "" else float(r["pue"]),
                })
        return rows

    def get_trajectory(self, plan_id: str) -> dict:
        pdir = self.plan_dir(plan_id) / "prevalidation"
        return {"nominal": self._read_traj_csv(pdir / "trajectory_ai.csv"),
                "worst": self._read_traj_csv(pdir / "trajectory_worst.csv")}
