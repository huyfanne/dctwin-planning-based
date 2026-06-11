"""Telemetry ingest + live-frame assembly (Tier A2).

No physical BMS exists on this rig, so everything is built against the *seam*:
``TelemetryStore`` accepts pushes from any historian (``POST /api/telemetry``) and
``SimTelemetryFeed`` self-generates the same point set with an explicit
``simulated=1.0`` label — switching to real data is just "stop starting the feed".
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel

N_RACKS = 22
RACK_INLET_PREFIX = "rack_inlet_c/"

# Alert lines against the hard 26 °C inlet cap (warn = margin < 1 °C).
INLET_WARN_C = 25.0
INLET_CRITICAL_C = 26.0

# Per-axis |held − commanded| tolerance for setpoint compliance.
COMPLIANCE_TOL = 0.5

# Held-setpoint telemetry points, keyed by compliance axis.
HELD_POINTS = {"sat": "held/sat_c", "flow": "held/flow_kg_s", "chwst": "held/chwst_c"}

# recommendation.json setpoint names -> compliance axes
_REC_SETPOINTS = {"sat": "crah_supply_air_temperature_c",
                  "flow": "crah_supply_air_mass_flow_rate_kg_s",
                  "chwst": "chilled_water_supply_temperature_c"}


class TelemetryIngest(BaseModel):
    """POST /api/telemetry body — the real-historian seam: a field collector pushes
    the same point names the sim feed generates."""
    ts: Optional[float] = None
    points: dict[str, float]


class TelemetryStore:
    """Append-only point telemetry in SQLite (same dir convention as PlanStore).
    Every method opens its own connection, so the daemon feed thread and request
    handlers can use one store instance concurrently."""

    def __init__(self, db_path: str = "runs/telemetry.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS telemetry "
                      "(ts REAL, point TEXT, value REAL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_point_ts "
                      "ON telemetry (point, ts)")

    def write(self, points: dict, ts: Optional[float] = None) -> float:
        """Insert one snapshot (all points share one ts) and return that ts."""
        ts = time.time() if ts is None else float(ts)
        with self._conn() as c:
            c.executemany("INSERT INTO telemetry (ts, point, value) VALUES (?, ?, ?)",
                          [(ts, str(k), float(v)) for k, v in points.items()])
        return ts

    def latest(self) -> dict:
        """{point: {"ts", "value"}} for the newest sample of every point. SQLite's
        bare-column-with-MAX semantics guarantee value comes from the max-ts row."""
        with self._conn() as c:
            rows = c.execute("SELECT point, MAX(ts) AS ts, value FROM telemetry "
                             "GROUP BY point").fetchall()
        return {r["point"]: {"ts": r["ts"], "value": r["value"]} for r in rows}

    @staticmethod
    def _stride(rows: list[dict], max_rows: int) -> list[dict]:
        """Downsample to ~max_rows by stride, always keeping the newest sample."""
        if len(rows) <= max_rows:
            return rows
        stride = math.ceil(len(rows) / max_rows)
        out = rows[::stride]
        if out[-1] is not rows[-1]:
            out.append(rows[-1])
        return out

    def series(self, points: list[str], minutes: float, max_rows: int = 400,
               now: Optional[float] = None) -> dict:
        """{point: [{"ts","value"}…]} over the trailing window, ascending,
        stride-downsampled per point. Absent points map to []."""
        now = time.time() if now is None else float(now)
        t0 = now - minutes * 60.0
        out = {}
        with self._conn() as c:
            for p in points:
                rows = c.execute("SELECT ts, value FROM telemetry "
                                 "WHERE point=? AND ts>=? ORDER BY ts", (p, t0)).fetchall()
                out[p] = self._stride([{"ts": r["ts"], "value": r["value"]}
                                       for r in rows], max_rows)
        return out

    def worst_inlet_series(self, minutes: float, max_rows: int = 400,
                           now: Optional[float] = None) -> list[dict]:
        """Worst (max) rack inlet per snapshot ts — server-side, so the UI never
        ships 22 separate series."""
        now = time.time() if now is None else float(now)
        t0 = now - minutes * 60.0
        with self._conn() as c:
            rows = c.execute("SELECT ts, MAX(value) AS value FROM telemetry "
                             "WHERE point LIKE ? AND ts>=? GROUP BY ts ORDER BY ts",
                             (RACK_INLET_PREFIX + "%", t0)).fetchall()
        return self._stride([{"ts": r["ts"], "value": r["value"]} for r in rows],
                            max_rows)


class SimTelemetryFeed:
    """Self-generated, explicitly labelled telemetry (``simulated=1.0`` rides in every
    snapshot) so the live dashboard works with no BMS attached. Base values are
    constants + a slow sinusoid + small noise — dependency-free by design; the
    nominal feed stays below the 25 °C warn line so it never cries wolf. ``now_fn``
    and ``rng`` are injectable so tests call ``snapshot()``/``_tick()`` directly and
    deterministically instead of running the thread."""

    _DEFAULT_HELD = {"sat": 24.0, "flow": 9.0, "chwst": 16.0}

    def __init__(self, store: TelemetryStore, interval_s: float = 5.0, *,
                 commanded_fn: Optional[Callable[[], Optional[dict]]] = None,
                 base_inlet_c: float = 23.2,
                 now_fn: Optional[Callable[[], float]] = None,
                 rng: Optional[random.Random] = None):
        self.store = store
        self.interval_s = float(interval_s)
        self.commanded_fn = commanded_fn or (lambda: None)
        self.base_inlet_c = float(base_inlet_c)
        self.now_fn = now_fn or time.time
        self.rng = rng or random.Random()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def snapshot(self, now: Optional[float] = None) -> dict:
        now = self.now_fn() if now is None else float(now)
        g = self.rng.gauss
        day = 2.0 * math.pi * now / 86400.0          # slow daily swing
        points = {}
        for i in range(1, N_RACKS + 1):
            spread = 0.8 * math.sin(0.7 * i)          # fixed per-rack offset
            wave = 0.5 * math.sin(day + 0.25 * i)
            points[f"{RACK_INLET_PREFIX}ite-{i}"] = round(
                self.base_inlet_c + spread + wave + g(0.0, 0.08), 3)
        points["hall_power_kw"] = round(480.0 + 30.0 * math.sin(day) + g(0.0, 4.0), 2)
        points["pue"] = round(1.32 + 0.03 * math.sin(day) + g(0.0, 0.005), 4)
        points["rh_pct"] = round(52.0 + 4.0 * math.sin(day / 2.0) + g(0.0, 0.5), 2)
        cmd = self.commanded_fn() or self._DEFAULT_HELD
        for axis, point in HELD_POINTS.items():
            points[point] = round(float(cmd[axis]) + g(0.0, 0.05), 3)
        points["simulated"] = 1.0                    # honesty label — never dropped
        return points

    def _tick(self) -> float:
        return self.store.write(self.snapshot(), ts=self.now_fn())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - a bad tick must not kill the feed
                pass
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="sim-telemetry-feed")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._thread = None


def commanded_setpoints(plan_store) -> Optional[dict]:
    """{"sat","flow","chwst"} from the newest *deployed* plan's recommendation —
    the compliance reference. None (never an error) when nothing is deployed."""
    try:
        for p in plan_store.list_plans():            # newest first
            if p.get("status") != "deployed":
                continue
            sp = (plan_store.get_recommendation(p["plan_id"]) or {}).get("setpoints") or {}
            if all(k in sp for k in _REC_SETPOINTS.values()):
                return {axis: float(sp[key]) for axis, key in _REC_SETPOINTS.items()}
    except Exception:  # noqa: BLE001
        pass
    return None


def compute_alerts(values: dict) -> list[dict]:
    """Rack-inlet alerts against the 26 °C cap: ≥ 25.0 warn (margin < 1 °C),
    ≥ 26.0 critical. Non-inlet points never alert."""
    alerts = []
    for point in sorted(values):
        if not point.startswith(RACK_INLET_PREFIX):
            continue
        v = float(values[point])
        if v >= INLET_CRITICAL_C:
            alerts.append({"level": "critical", "point": point, "value": v,
                           "message": f"inlet {v:.1f} °C at/above the 26 °C cap"})
        elif v >= INLET_WARN_C:
            alerts.append({"level": "warn", "point": point, "value": v,
                           "message": f"inlet {v:.1f} °C — margin < 1 °C to the 26 °C cap"})
    return alerts


def compute_compliance(commanded: Optional[dict], values: dict) -> dict:
    """Commanded (deployed plan) vs held (telemetry) setpoints, tolerance 0.5 per
    axis. ok is None when either side is missing — unknown, not green."""
    held = {axis: values[pt] for axis, pt in HELD_POINTS.items() if pt in values} or None
    if commanded is None or held is None:
        return {"commanded": commanded, "held": held, "ok": None, "deltas": {}}
    deltas, ok = {}, True
    for axis in HELD_POINTS:
        c, h = commanded.get(axis), held.get(axis)
        if c is None or h is None:
            deltas[axis] = None
            continue
        deltas[axis] = round(float(h) - float(c), 3)
        if abs(deltas[axis]) > COMPLIANCE_TOL:
            ok = False
    return {"commanded": commanded, "held": held, "ok": ok, "deltas": deltas}


def live_frame(store: TelemetryStore, commanded: Optional[dict] = None) -> dict:
    """One GET /api/live payload: latest points + alerts + compliance + the
    simulated label (true when the sim feed wrote the newest data)."""
    latest = store.latest()
    values = {k: v["value"] for k, v in latest.items()}
    return {"ts": max((v["ts"] for v in latest.values()), default=None),
            "points": latest,
            "alerts": compute_alerts(values),
            "compliance": compute_compliance(commanded, values),
            "simulated": values.get("simulated", 0.0) >= 0.5}


_LIVE_POLL_S = 1.0
_LIVE_MAX_ITERS = 7200             # ~2 h backstop at 1 s (mirrors plan_sse_stream)
_LIVE_KEEPALIVE_EVERY = 15         # ~15 s idle -> SSE comment so proxies keep it open


async def live_sse_stream(frame_fn: Callable[[], dict], is_disconnected, *,
                          sleep=asyncio.sleep, max_iters: Optional[int] = None,
                          keepalive_every: Optional[int] = None):
    """Yield SSE chunks of the live frame until the client disconnects or the
    (generous) backstop is hit — the poll-diff/keepalive pattern of
    ``main.plan_sse_stream``, minus the terminal-status exit (live never ends).

    The backstops resolve at CALL time so tests can shrink the module constants:
    a live stream has no terminal state, and TestClient teardown deadlocks
    waiting on a generator that never observed the disconnect."""
    max_iters = _LIVE_MAX_ITERS if max_iters is None else max_iters
    keepalive_every = _LIVE_KEEPALIVE_EVERY if keepalive_every is None else keepalive_every
    last = None
    since = 0
    for _ in range(max_iters):
        if await is_disconnected():
            break
        frame = frame_fn()
        if frame != last:
            yield f"data: {json.dumps(frame)}\n\n"
            last = frame
            since = 0
        else:
            since += 1
            if since >= keepalive_every:
                yield ": keepalive\n\n"
                since = 0
        await sleep(_LIVE_POLL_S)
