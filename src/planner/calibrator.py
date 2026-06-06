"""Output-residual calibration: learn per-KPI bias + uncertainty from the deploy
loop's paired (predicted, realized) history, and correct twin predictions toward
the (perturbed) plant. P2a — the residual stage; P2b consumes sigma for robustness."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from planner.types import WeeklyKPI

CALIB_KEYS = ("total_hvac_energy_kwh", "pue_mean", "inlet_temp_max_c")
_KEY_TO_FIELD = {
    "total_hvac_energy_kwh": "total_hvac_energy_kwh",
    "pue_mean": "pue_mean",
    "inlet_temp_max_c": "inlet_temp_max",
}


@dataclass(frozen=True)
class Calibration:
    bias: dict
    sigma: dict
    n_weeks: int
    version: str

    @staticmethod
    def identity() -> "Calibration":
        return Calibration(bias={}, sigma={}, n_weeks=0, version="weeks-0")

    def apply(self, kpi: WeeklyKPI) -> WeeklyKPI:
        updates = {}
        for key, field in _KEY_TO_FIELD.items():
            b = self.bias.get(key)
            if b:
                updates[field] = getattr(kpi, field) + b
        return dataclasses.replace(kpi, **updates) if updates else kpi

    def sigma_for(self, key: str) -> float:
        return self.sigma.get(key, 0.0)

    def to_dict(self) -> dict:
        return {"bias": self.bias, "sigma": self.sigma,
                "n_weeks": self.n_weeks, "version": self.version}

    @staticmethod
    def from_dict(d: dict) -> "Calibration":
        return Calibration(bias=d.get("bias", {}), sigma=d.get("sigma", {}),
                           n_weeks=int(d.get("n_weeks", 0)),
                           version=d.get("version", f"weeks-{int(d.get('n_weeks', 0))}"))


def fit_calibration(history: list) -> Calibration:
    bias, sigma = {}, {}
    for key in CALIB_KEYS:
        res = []
        for e in history:
            p = e.get("predicted", {}).get(key)
            r = e.get("realized", {}).get(key)
            if p is not None and r is not None:
                res.append(r - p)
        if res:
            m = sum(res) / len(res)
            bias[key] = m
            sigma[key] = (sum((x - m) ** 2 for x in res) / len(res)) ** 0.5 if len(res) > 1 else 0.0
    n = len(history)
    return Calibration(bias=bias, sigma=sigma, n_weeks=n, version=f"weeks-{n}")


def load_calibration(path: str = "data/calibration.json") -> Calibration:
    p = Path(path)
    return Calibration.from_dict(json.loads(p.read_text())) if p.exists() else Calibration.identity()


def save_calibration(cal: Calibration, path: str = "data/calibration.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cal.to_dict(), indent=2))


def recompute_calibration(history_path: str = "data/calibration_history.json",
                          out_path: str = "data/calibration.json") -> Calibration:
    """Re-fit the Calibration from the paired history and persist it."""
    hp = Path(history_path)
    hist = json.loads(hp.read_text()) if hp.exists() else []
    cal = fit_calibration(hist)
    save_calibration(cal, out_path)
    return cal
