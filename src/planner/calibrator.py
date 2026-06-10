"""Output-residual calibration: learn per-KPI bias + uncertainty from the deploy
loop's paired (predicted, realized) history, and correct twin predictions toward
the (perturbed) plant. P2a — the residual stage; P2b consumes sigma for robustness."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from planner.types import WeeklyKPI

CALIB_KEYS = ("total_hvac_energy_kwh", "pue_mean", "inlet_temp_max_c")
_KEY_TO_FIELD = {
    "total_hvac_energy_kwh": "total_hvac_energy_kwh",
    "pue_mean": "pue_mean",
    "inlet_temp_max_c": "inlet_temp_max",
}

# Conservative per-KPI prior sigma (a floor at cold-start) and per-residual clip
# (winsorize so one wild week can't dominate the bias). Spec §6.1.
SIGMA_PRIOR = {"total_hvac_energy_kwh": 5000.0, "pue_mean": 0.05, "inlet_temp_max_c": 1.0}
RESIDUAL_CLIP = {"total_hvac_energy_kwh": 50000.0, "pue_mean": 0.5, "inlet_temp_max_c": 3.0}


@dataclass(frozen=True)
class Calibration:
    bias: dict
    sigma: dict
    n_weeks: int
    version: str
    # Empirical-Bayes posterior error scale: sqrt((n*s^2 + prior^2)/(n+1)) — the prior
    # counts as ONE pseudo-week of evidence, so measured accuracy tightens it smoothly
    # (n=0 -> prior; n=1,s~0 -> prior/sqrt(2); n->inf -> s). Used to size the robust
    # ensemble. Distinct from `sigma` (fading floor max(s, prior/n)), which backs the
    # nominal k*sigma margin and deliberately never under-states error at small n.
    sigma_post: dict = dataclasses.field(default_factory=dict)

    @staticmethod
    def identity() -> "Calibration":
        return Calibration(bias={}, sigma={}, n_weeks=0, version="weeks-0")

    def apply(self, kpi: WeeklyKPI, inlet_cap: float = 26.0) -> WeeklyKPI:
        updates = {}
        for key, field in _KEY_TO_FIELD.items():
            b = self.bias.get(key)
            if b:
                updates[field] = getattr(kpi, field) + b
        if not updates:
            return kpi
        # Safety: a bias-on-max can't reconstruct a per-step count, so if the
        # CORRECTED peak inlet breaches the cap, flag the candidate infeasible
        # (>=1 violation step) so the objective's feasibility gate rejects it.
        corrected_inlet = updates.get("inlet_temp_max")
        if corrected_inlet is not None and corrected_inlet > inlet_cap:
            updates["inlet_violation_steps"] = max(kpi.inlet_violation_steps, 1)
        return dataclasses.replace(kpi, **updates)

    def sigma_for(self, key: str) -> float:
        return self.sigma.get(key, 0.0)

    def sigma_post_for(self, key: str) -> float:
        """Posterior error scale for ensemble sizing; a calibration file written before
        sigma_post existed falls back to the (floor-pinned) sigma — never less conservative
        than the old behavior."""
        v = self.sigma_post.get(key)
        return float(v) if v is not None else self.sigma_for(key)

    def to_dict(self) -> dict:
        return {"bias": self.bias, "sigma": self.sigma, "sigma_post": self.sigma_post,
                "n_weeks": self.n_weeks, "version": self.version}

    @staticmethod
    def from_dict(d: dict) -> "Calibration":
        return Calibration(bias=d.get("bias", {}), sigma=d.get("sigma", {}),
                           n_weeks=int(d.get("n_weeks", 0)),
                           version=d.get("version", f"weeks-{int(d.get('n_weeks', 0))}"),
                           sigma_post=d.get("sigma_post", {}))


def fit_calibration(history: list) -> Calibration:
    bias, sigma, sigma_post = {}, {}, {}
    for key in CALIB_KEYS:
        clip = RESIDUAL_CLIP.get(key, float("inf"))
        res = []
        for e in history:
            p = e.get("predicted", {}).get(key)
            r = e.get("realized", {}).get(key)
            if p is not None and r is not None:
                res.append(max(-clip, min(clip, r - p)))   # winsorized residual
        if res:
            m = sum(res) / len(res)
            bias[key] = m
            n = len(res)
            sample = (sum((x - m) ** 2 for x in res) / n) ** 0.5
            prior = SIGMA_PRIOR.get(key, 0.0)
            # Fading floor: a conservative prior that decays as 1/n toward the
            # empirical sample std. At n=1 sample=0 so sigma=prior (never the
            # sigma=0 cold-start poison); as weeks accumulate prior/n -> 0 and the
            # sample std takes over. max() keeps it monotonically shrinking.
            sigma[key] = max(sample, prior / n)
            # Empirical-Bayes posterior: prior = one pseudo-week. Smoothly blends the
            # measured residual spread with the prior, so observed accuracy tightens
            # the robust ensemble without ever collapsing it on thin evidence.
            sigma_post[key] = ((n * sample ** 2 + prior ** 2) / (n + 1)) ** 0.5
    n = len(history)
    return Calibration(bias=bias, sigma=sigma, n_weeks=n, version=f"weeks-{n}",
                       sigma_post=sigma_post)


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
