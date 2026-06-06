"""P2c seam: future EnergyPlus parameter recalibration — tune the twin's physical
params toward the plant once enough realized weeks accumulate (drift-triggered).
v1 is a documented NO-OP; the P2a output-residual Calibration covers the gap until
this is implemented. Wiring a real implementation behind this signature is P2c."""
from __future__ import annotations

from typing import Optional

from planner.calibrator import Calibration


def recalibrate(calibration: Calibration, history: list,
                min_weeks: int = 8) -> Optional[dict]:
    """Return EnergyPlus model-parameter updates once enough realized weeks +
    drift warrant a physics recalibration; v1 always returns None (seam only)."""
    return None
