from datetime import date

from planner.week_config import compute_week_period, WeekPeriod


def test_week_period_inclusive_seven_days():
    p = compute_week_period(date(2013, 11, 11), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=11, end_month=11, end_day=17)


def test_week_period_crosses_month():
    p = compute_week_period(date(2013, 11, 28), days=7)
    assert p == WeekPeriod(begin_month=11, begin_day=28, end_month=12, end_day=4)


def test_week_period_rejects_year_wrap():
    import pytest
    with pytest.raises(ValueError):
        compute_week_period(date(2013, 12, 30), days=7)
