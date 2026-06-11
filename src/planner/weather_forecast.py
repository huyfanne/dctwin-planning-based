"""Weather forecast + uncertainty from the historical EPW (Stage 6, item #7).

Without an external forecast provider, the honest short-horizon uncertainty for the
target week is the *historical-analog spread*: the dry-bulb mean/std over the same
month-days padded +-7 days in the EPW, matched year-agnostically. `weather_scenarios`
turns that spread into nominal/hot/cool EPW variants so the robust rerank can treat
weather uncertainty exactly like plant uncertainty.

Real-forecast-API seam: `weather_stats` is the only function that *estimates* the
week's weather. To plug in a provider (e.g. an NWP/forecast vendor), replace this
function — or just its return value — with the provider's mean/sigma for the target
week using the same ``{"mean_c", "sigma_c", "n"}`` shape; `write_epw_variant`,
`weather_scenarios`, and everything downstream (robust rerank, deploy gate) are
unchanged.

EPW layout (see planner.epw): 8 header lines, then CSV rows
``year,month,day,hour,minute,source,dry_bulb@idx6,dew_point@idx7,...``.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import fmean, pstdev

from planner.epw import _md_in_range

_N_HEADER_LINES = 8
_DRY_BULB = 6
_DEW_POINT = 7
_PAD_DAYS = 7


def weather_stats(epw_path: str, week_start: date, days: int = 7) -> dict:
    """Dry-bulb mean/std over the target week's month-days padded +-7 days.

    Month-day matching is year-agnostic (and handles a year wrap, e.g. a January
    week against a Nov-Jan EPW). Returns {"mean_c", "sigma_c", "n"}; raises
    ValueError when no EPW rows fall inside the window."""
    lo = week_start - timedelta(days=_PAD_DAYS)
    hi = week_start + timedelta(days=days - 1 + _PAD_DAYS)
    start_md, end_md = (lo.month, lo.day), (hi.month, hi.day)
    temps: list[float] = []
    for line in Path(epw_path).read_text().splitlines()[_N_HEADER_LINES:]:
        f = line.split(",")
        if len(f) <= _DRY_BULB:
            continue
        try:
            md = (int(f[1]), int(f[2]))
            temp = float(f[_DRY_BULB])
        except ValueError:
            continue
        if _md_in_range(md, start_md, end_md):
            temps.append(temp)
    if not temps:
        raise ValueError(
            f"no EPW rows within +-{_PAD_DAYS} days of {week_start} (+{days}d) in {epw_path}")
    sigma = pstdev(temps) if len(temps) > 1 else 0.0
    return {"mean_c": fmean(temps), "sigma_c": sigma, "n": len(temps)}


def write_epw_variant(epw_path: str, out_path: str, delta_c: float) -> str:
    """Copy the EPW with dry-bulb (idx 6) shifted by `delta_c`, clamping dew-point
    (idx 7) <= the shifted dry-bulb. Headers and every other field (including line
    endings) are preserved byte-exact. Creates parent dirs. Returns `out_path`."""
    out_lines: list[str] = []
    for i, line in enumerate(Path(epw_path).read_text().splitlines(keepends=True)):
        if i < _N_HEADER_LINES:
            out_lines.append(line)
            continue
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        f = body.split(",")
        if len(f) <= _DRY_BULB:
            out_lines.append(line)
            continue
        try:
            dry = float(f[_DRY_BULB]) + delta_c
        except ValueError:
            out_lines.append(line)
            continue
        f[_DRY_BULB] = f"{dry:.1f}"
        if len(f) > _DEW_POINT:
            try:
                if float(f[_DEW_POINT]) > dry:
                    f[_DEW_POINT] = f"{dry:.1f}"
            except ValueError:
                pass
        out_lines.append(",".join(f) + eol)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(out_lines))
    return str(out)


def weather_scenarios(epw_path: str, week_start: date, out_dir: str, k: float = 1.0) -> list[dict]:
    """Nominal/hot/cool weather scenarios for the target week: hot/cool shift
    dry-bulb by +-k*sigma_c (the historical-analog spread from `weather_stats`).
    Writes the variant EPWs into `out_dir` (created if missing) and returns
    [{"label", "epw", "delta_c"}, ...] with nominal pointing at the original EPW."""
    delta = k * weather_stats(epw_path, week_start)["sigma_c"]
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    scenarios = [{"label": "nominal", "epw": str(epw_path), "delta_c": 0.0}]
    for label, delta_c in (("hot", +delta), ("cool", -delta)):
        epw = write_epw_variant(epw_path, str(d / f"{label}.epw"), delta_c)
        scenarios.append({"label": label, "epw": epw, "delta_c": delta_c})
    return scenarios
