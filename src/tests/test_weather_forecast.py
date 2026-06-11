from datetime import date
from pathlib import Path

import pytest

from planner.epw import weather_timeseries
from planner.weather_forecast import weather_scenarios, weather_stats, write_epw_variant

_HEADER = ["LOCATION,Test,,,,,,,0,0,0,0"] + [f"H{i}" for i in range(6)] + [
    "DATA PERIODS,1,1,Data,Sunday, 11/ 1, 11/30"]


def _write_epw(tmp_path: Path, rows: list[str], name: str = "t.epw") -> str:
    p = tmp_path / name
    p.write_text("\n".join(_HEADER + rows) + "\n")
    return str(p)


def _stats_rows() -> list[str]:
    # Nov 1-30 2023, 24 hourly rows/day. Inside the padded window for a Nov 15
    # week (+-7 days => Nov 8..28) temps alternate 26/30 (mean 28, pstdev 2);
    # outside it they are 50.0, so any window leak corrupts the mean.
    rows = []
    for d in range(1, 31):
        for h in range(1, 25):
            temp = 50.0 if d < 8 or d > 28 else (26.0 if h % 2 else 30.0)
            rows.append(f"2023,11,{d},{h},0,C9,{temp:.1f},20.0,80,101325")
    return rows


def test_weather_stats_known_mean_std_and_window(tmp_path):
    epw = _write_epw(tmp_path, _stats_rows())
    s = weather_stats(epw, date(2024, 11, 15), days=7)   # rows are 2023: md match is year-agnostic
    assert s["n"] == 21 * 24                             # Nov 8..28 only (week +-7 days)
    assert s["mean_c"] == pytest.approx(28.0)
    assert s["sigma_c"] == pytest.approx(2.0)


def test_weather_stats_year_wrap_window(tmp_path):
    rows = []
    for d in range(20, 32):   # Dec 20..31; 20..25 fall outside the padded window
        temp = 50.0 if d < 26 else 25.0
        rows.append(f"2023,12,{d},1,0,C9,{temp:.1f},20.0")
    for d in range(1, 16):    # Jan 1..15 all inside
        rows.append(f"2024,1,{d},1,0,C9,25.0,20.0")
    epw = _write_epw(tmp_path, rows)
    s = weather_stats(epw, date(2024, 1, 2), days=7)     # window Dec 26 .. Jan 15 (wraps the year)
    assert s["n"] == 6 + 15
    assert s["mean_c"] == pytest.approx(25.0)
    assert s["sigma_c"] == pytest.approx(0.0)


def test_weather_stats_empty_window_raises(tmp_path):
    epw = _write_epw(tmp_path, ["2023,11,1,1,0,C9,27.0,20.0"])
    with pytest.raises(ValueError):
        weather_stats(epw, date(2024, 6, 1), days=7)


def test_write_epw_variant_shifts_and_clamps_dewpoint(tmp_path):
    rows = [
        "2024,11,1,1,0,C9,27.0,26.5,80,101325",   # dew 26.5 > 25.0 after shift -> clamped
        "2024,11,1,2,0,C9,24.0,18.5,81,101300",   # dew 18.5 <= 22.0 -> untouched byte-exact
    ]
    epw = _write_epw(tmp_path, rows)
    out = tmp_path / "v" / "cool.epw"             # parent dir does not exist yet
    assert write_epw_variant(epw, str(out), -2.0) == str(out)

    src_lines = Path(epw).read_text().splitlines()
    out_lines = out.read_text().splitlines()
    assert out_lines[:8] == src_lines[:8]         # headers byte-exact
    f1, f2 = out_lines[8].split(","), out_lines[9].split(",")
    assert f1[6] == "25.0" and f1[7] == "25.0"    # shifted, dew clamped to dry-bulb
    assert f2[6] == "22.0" and f2[7] == "18.5"    # shifted, dew untouched
    for got, src in zip(out_lines[8:], src_lines[8:]):
        g, s = got.split(","), src.split(",")
        assert g[:6] == s[:6] and g[8:] == s[8:]  # every other field byte-exact

    ts = weather_timeseries(str(out), date(2024, 11, 1), days=1)   # variant still parses
    assert [p["temp_c"] for p in ts] == [25.0, 22.0]


def test_write_epw_variant_positive_shift_no_clamp(tmp_path):
    epw = _write_epw(tmp_path, ["2024,11,1,1,0,C9,27.0,26.5,80,101325"])
    out = str(tmp_path / "hot.epw")
    write_epw_variant(epw, out, 1.5)
    f = Path(out).read_text().splitlines()[8].split(",")
    assert f[6] == "28.5" and f[7] == "26.5"


def test_weather_scenarios_shape_deltas_and_out_dir(tmp_path):
    epw = _write_epw(tmp_path, _stats_rows())
    out_dir = tmp_path / "scen" / "w1"            # nested, does not exist yet
    scen = weather_scenarios(epw, date(2024, 11, 15), str(out_dir), k=2.0)

    assert [s["label"] for s in scen] == ["nominal", "hot", "cool"]
    assert scen[0]["epw"] == epw and scen[0]["delta_c"] == 0.0
    assert scen[1]["delta_c"] == pytest.approx(+2.0 * 2.0)        # +k*sigma (sigma=2)
    assert scen[2]["delta_c"] == pytest.approx(-2.0 * 2.0)        # -k*sigma
    assert out_dir.is_dir()
    for s in scen[1:]:
        assert Path(s["epw"]).is_file()

    ts = weather_timeseries(scen[1]["epw"], date(2023, 11, 8), days=1)
    assert ts[0]["temp_c"] == pytest.approx(26.0 + 4.0)           # hot variant really shifted
