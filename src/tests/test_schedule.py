from planner.schedule import TimeBlock, WeeklySchedule, DEFAULT_BLOCKS
from planner.types import Setpoints


def test_timeblock_contains_non_wrap():
    day = TimeBlock("day", 6, 18)
    assert day.contains(6) and day.contains(12) and day.contains(17)
    assert not day.contains(5) and not day.contains(18) and not day.contains(23)


def test_timeblock_contains_wrap():
    night = TimeBlock("night", 18, 6)        # wraps midnight
    assert night.contains(18) and night.contains(23) and night.contains(0) and night.contains(5)
    assert not night.contains(6) and not night.contains(12)


def test_default_blocks_partition_the_day():
    sched = WeeklySchedule(DEFAULT_BLOCKS, (Setpoints(24, 8, 17), Setpoints(25, 7, 16)))
    # every hour maps to exactly one block; day=0 (06-18), night=1 (18-06)
    assert [sched.block_for_hour(h) for h in (0, 5, 6, 12, 17, 18, 23)] == [1, 1, 0, 0, 0, 1, 1]


def test_schedule_length_invariant():
    import pytest
    with pytest.raises(ValueError):
        WeeklySchedule(DEFAULT_BLOCKS, (Setpoints(24, 8, 17),))   # 2 blocks, 1 setpoint
