from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


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
        (self.plan_dir(plan_id) / "recommendation.json").write_text(json.dumps(rec, indent=2))
        kpis = rec.get("predicted_kpis") or {}
        with self._conn() as c:
            c.execute(
                "UPDATE plans SET status=?, energy_kwh=?, reduction_pct=? WHERE plan_id=?",
                (rec.get("status"), kpis.get("total_hvac_energy_kwh"),
                 kpis.get("energy_reduction_vs_baseline_pct"), plan_id),
            )

    def get_recommendation(self, plan_id: str) -> Optional[dict]:
        p = self.plan_dir(plan_id) / "recommendation.json"
        return json.loads(p.read_text()) if p.exists() else None

    def save_realized(self, plan_id: str, realized: dict) -> None:
        (self.plan_dir(plan_id) / "realized.json").write_text(json.dumps(realized, indent=2))

    def get_realized(self, plan_id: str) -> Optional[dict]:
        p = self.plan_dir(plan_id) / "realized.json"
        return json.loads(p.read_text()) if p.exists() else None

    def write_progress(self, plan_id: str, progress: dict) -> None:
        # Non-finite floats (e.g. best_score = +inf when all candidates are
        # infeasible) are invalid JSON and break the API response; store as null.
        safe = {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in progress.items()}
        (self.plan_dir(plan_id) / "progress.json").write_text(json.dumps(safe))

    def read_progress(self, plan_id: str) -> dict:
        p = self.plan_dir(plan_id) / "progress.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text())
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
