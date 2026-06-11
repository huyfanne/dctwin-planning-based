from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

HOURS_PER_DAY = 24


@dataclass(frozen=True)
class Tariff:
    """Hourly objective weights for the energy term.

    `rates` is 24 floats indexed by hour-of-day: an electricity price ($/kWh)
    or a carbon intensity (kgCO2/kWh). `kind` is a free-form label surfaced in
    the recommendation so a reader knows what the weighted cost means.
    """

    kind: str
    rates: tuple  # 24 floats, index = hour of day


def load_tariff(path: str = "data/tariff.json") -> Optional[Tariff]:
    """Load the operator-provided tariff file; absent or invalid -> None.

    None means "no tariff": every downstream consumer must behave exactly as
    today (raw-energy objective). Never raise — a bad tariff file must not
    break planning, only be ignored (with a log line).
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        kind = str(data.get("kind", "tariff"))
        raw = data["rates"]
        if not isinstance(raw, (list, tuple)):
            raise TypeError(f"rates must be a list, got {type(raw).__name__}")
        rates = tuple(float(r) for r in raw)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        log.warning("tariff: ignoring invalid %s (%s)", path, exc)
        return None
    if len(rates) != HOURS_PER_DAY or not all(math.isfinite(r) for r in rates):
        log.warning("tariff: ignoring %s — need %d finite hourly rates, got %d",
                    path, HOURS_PER_DAY, len(rates))
        return None
    return Tariff(kind=kind, rates=rates)
