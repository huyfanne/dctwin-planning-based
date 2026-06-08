from __future__ import annotations

from dataclasses import dataclass

from planner.types import Setpoints


@dataclass(frozen=True)
class TimeBlock:
    """A daily time window [start_hour, end_hour) in local hours. end <= start wraps midnight."""
    label: str
    start_hour: int
    end_hour: int

    def contains(self, hour: int) -> bool:
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour   # wrap (e.g. 18->06)


@dataclass(frozen=True)
class WeeklySchedule:
    """A per-time-block setpoint schedule. `setpoints[i]` applies during `blocks[i]`."""
    blocks: tuple[TimeBlock, ...]
    setpoints: tuple[Setpoints, ...]

    def __post_init__(self) -> None:
        if len(self.blocks) != len(self.setpoints):
            raise ValueError(
                f"blocks ({len(self.blocks)}) and setpoints ({len(self.setpoints)}) length mismatch")

    def block_for_hour(self, hour: int) -> int:
        """Index of the block covering `hour` (first match wins; falls back to 0)."""
        for i, b in enumerate(self.blocks):
            if b.contains(hour):
                return i
        return 0


DEFAULT_BLOCKS = (TimeBlock("day", 6, 18), TimeBlock("night", 18, 6))
