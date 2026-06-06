from datetime import date
from planner.epw import epw_data_period, week_within_epw

_HEADER = (
    "LOCATION,Singapore Changi,-,SGP,NASA POWER,486980,1.367,103.983,8.0,16.0\n"
    "DESIGN CONDITIONS,0\nTYPICAL/EXTREME PERIODS,0\nGROUND TEMPERATURES,0\n"
    "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0\nCOMMENTS 1,\nCOMMENTS 2,\n"
    "DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31\n"
)


def _write_epw(tmp_path):
    p = tmp_path / "w.epw"
    p.write_text(_HEADER + "2024,11,1,1,60,_,27.1\n")
    return str(p)


def test_epw_data_period_parses_start_end(tmp_path):
    assert epw_data_period(_write_epw(tmp_path)) == ((11, 1), (1, 31))


def test_week_within_epw_handles_year_wrap(tmp_path):
    epw = _write_epw(tmp_path)
    assert week_within_epw(epw, date(2024, 11, 11), days=7) is True
    assert week_within_epw(epw, date(2025, 1, 10), days=7) is True
    assert week_within_epw(epw, date(2024, 6, 1), days=7) is False
