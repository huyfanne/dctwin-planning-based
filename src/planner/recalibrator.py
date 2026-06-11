"""P2c physics re-calibration (Stage 6 #5): tune the twin's plant parameters toward
the measured plant once enough realized weeks accumulate. A persistent energy bias
fraction b = mean(realized/predicted) - 1 maps to a fan-efficiency correction
factor = clip(1/(1+b), 0.85, 1.15): more realized energy than predicted means the
real fans are LESS efficient than modeled. Conservative, explainable, monotone.

The deploy loop (webapp/jobs.write_plant_calibration, right after
recompute_calibration) persists the proposal to data/plant_calibration.json;
planner.plant.load_plant_config merges it over DEFAULT_PLANT, recentering the
robust ensemble on the data-driven believed plant state (#9)."""
from __future__ import annotations

from typing import Optional

from planner.calibrator import Calibration

ENERGY_KEY = "total_hvac_energy_kwh"
RATIO_CLIP = (0.5, 2.0)      # winsorize each weekly realized/predicted ratio
FACTOR_CLIP = (0.85, 1.15)   # never propose more than a +/-15% efficiency change
MIN_ABS_BIAS = 0.01          # |b| < 1% -> no actionable drift


def fit_plant_factors(history: list, min_weeks: int = 4) -> Optional[dict]:
    """Estimate a fan-efficiency correction from the paired (predicted, realized)
    energy history (entries: {week_start, predicted: {...}, realized: {...}}).

    Each weekly ratio realized/predicted is winsorized to RATIO_CLIP so one wild
    week can't dominate; b = mean(ratios) - 1 is the persistent energy bias.
    Returns None below `min_weeks` valid pairs or when |b| < 1% (no actionable
    drift); otherwise {"fan_total_efficiency_factor", "bias_fraction", "n_weeks"}.
    """
    ratios = []
    for entry in history:
        p = (entry.get("predicted") or {}).get(ENERGY_KEY)
        r = (entry.get("realized") or {}).get(ENERGY_KEY)
        if p and r is not None and p > 0:
            ratios.append(max(RATIO_CLIP[0], min(RATIO_CLIP[1], r / p)))
    if len(ratios) < min_weeks:
        return None
    b = sum(ratios) / len(ratios) - 1.0
    if abs(b) < MIN_ABS_BIAS:
        return None
    factor = max(FACTOR_CLIP[0], min(FACTOR_CLIP[1], 1.0 / (1.0 + b)))
    return {"fan_total_efficiency_factor": factor, "bias_fraction": b,
            "n_weeks": len(ratios)}


def recalibrate(calibration: Calibration, history: list,
                min_weeks: int = 4) -> Optional[dict]:
    """Return the EnergyPlus model-parameter update proposal once enough realized
    weeks show actionable drift, else None. Shape matches planner.plant's
    Perturbation fields, so load_plant_config can merge it over DEFAULT_PLANT:
    {"perturbations": [{"table", "field", "factor"}], "basis": {...}}."""
    fitted = fit_plant_factors(history, min_weeks=min_weeks)
    if fitted is None:
        return None
    return {
        "perturbations": [{
            "table": "Fan_VariableVolume",
            "field": "fan_total_efficiency",
            "factor": fitted["fan_total_efficiency_factor"],
        }],
        "basis": {
            "method": "winsorized_energy_ratio_v1",
            "bias_fraction": fitted["bias_fraction"],
            "n_weeks": fitted["n_weeks"],
            "calibration_version": getattr(calibration, "version", None),
        },
    }
