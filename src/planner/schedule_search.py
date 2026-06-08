"""Warm-start day/night schedule refinement (sub-project B). Stage 2 of the time-block plan:
seed the schedule at the (already-robust) constant winner, then locally refine each block."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from planner.objective import ObjectiveWeights, score
from planner.schedule import DEFAULT_BLOCKS, WeeklySchedule
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints, WeeklyKPI


@dataclass
class ScheduleResult:
    schedule: WeeklySchedule
    kpi: WeeklyKPI          # calibrated (twin's best estimate)
    kpi_raw: WeeklyKPI      # uncalibrated


def _neighbors(sched: WeeklySchedule, step: np.ndarray) -> list[WeeklySchedule]:
    space = DEFAULT_SEARCH_SPACE
    base = [list(sp.as_tuple()) for sp in sched.setpoints]
    out: list[WeeklySchedule] = []
    for b in range(len(sched.blocks)):
        for c in range(3):
            for sign in (1.0, -1.0):
                pert = [row[:] for row in base]
                pert[b][c] += sign * step[c]
                sps = tuple(space.clip(Setpoints(float(p[0]), float(p[1]), float(p[2]))) for p in pert)
                out.append(WeeklySchedule(sched.blocks, sps))
    return out


def refine_schedule(constant: Setpoints, evaluator, weights: ObjectiveWeights, forecast,
                    calibration, blocks=DEFAULT_BLOCKS, levels: int = 2) -> ScheduleResult:
    """Warm-start: seed at (constant,...) per block, then coordinate-descent refine over `levels`
    halving steps. Uses the same objective + (margin-adjusted) weights + calibration as the search.
    The seed is always evaluated first, so the result is NEVER worse than the constant."""
    space = DEFAULT_SEARCH_SPACE
    seed = WeeklySchedule(blocks, tuple(constant for _ in blocks))
    step = np.array([(space.sat.ub - space.sat.lb) / 4.0,
                     (space.flow.ub - space.flow.lb) / 4.0,
                     (space.chwst.ub - space.chwst.lb) / 4.0])

    def evaluate(scheds: list[WeeklySchedule]):
        """Score a whole batch of schedules in ONE evaluator call so the oracle can fan the
        independent candidates across its process pool (mirrors BeamPlanner._score_batch)."""
        raws = evaluator.evaluate_schedules(scheds, forecast)
        cals = [calibration.apply(r) for r in raws] if calibration is not None else raws
        return [(score(kpi, weights), kpi, raw) for kpi, raw in zip(cals, raws)]

    best_score, best_kpi, best_raw = evaluate([seed])[0]
    best, cur = seed, seed
    for _ in range(levels):
        neighbors = _neighbors(cur, step)
        for sched, (sc, kpi, raw) in zip(neighbors, evaluate(neighbors)):
            if sc < best_score:
                best_score, best_kpi, best_raw, best = sc, kpi, raw, sched
        cur = best
        step = step / 2.0
    return ScheduleResult(best, best_kpi, best_raw)
