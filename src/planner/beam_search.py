from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import numpy as np

from planner.objective import INFEASIBLE, ObjectiveWeights, score
from planner.types import Evaluator, SearchSpace, Setpoints, WeeklyKPI


@dataclass(frozen=True)
class BeamConfig:
    grid: int = 5            # g: coarse grid points per dim
    beam_width: int = 5      # B: frontier size kept each level
    levels: int = 3          # L: refine levels after the coarse grid
    neighbors: int = 8       # local samples per beam node per refine level
    max_evals: int = 400     # hard cap on total evaluations
    epsilon: float = 1e-3    # early-stop best-score improvement threshold


@dataclass
class PlanResult:
    best: Setpoints
    best_kpi: WeeklyKPI
    best_score: float
    evals: int
    feasible: bool
    history: list[float]     # best score after each level


# a scored candidate: (setpoints, kpi, score)
_Scored = tuple[Setpoints, WeeklyKPI, float]


def _coarse_grid(space: SearchSpace, g: int) -> list[Setpoints]:
    sats = np.linspace(space.sat.lb, space.sat.ub, g)
    flows = np.linspace(space.flow.lb, space.flow.ub, g)
    chwsts = np.linspace(space.chwst.lb, space.chwst.ub, g)
    return [
        Setpoints(float(a), float(b), float(c))
        for a, b, c in itertools.product(sats, flows, chwsts)
    ]


class BeamPlanner:
    def __init__(
        self,
        space: SearchSpace,
        evaluator: Evaluator,
        weights: Optional[ObjectiveWeights] = None,
        config: Optional[BeamConfig] = None,
    ):
        self.space = space
        self.evaluator = evaluator
        self.weights = weights or ObjectiveWeights()
        self.config = config or BeamConfig()

    def plan(self, forecast: Optional[Any] = None,
             on_level: Optional[Callable[[int, int, float], None]] = None) -> PlanResult:
        cfg = self.config
        if cfg.grid < 2:
            raise ValueError("BeamConfig.grid must be >= 2")

        evals = 0
        history: list[float] = []

        # ---- Level 0: coarse grid (also capped by max_evals) ----
        candidates = _coarse_grid(self.space, cfg.grid)
        if len(candidates) > cfg.max_evals:
            # uniform stride subsample spans the full range of every dim
            # (a head-slice of the lexicographic product would drop the high
            #  end of the first dimension entirely)
            stride = math.ceil(len(candidates) / cfg.max_evals)
            candidates = candidates[::stride][: cfg.max_evals]
        scored = self._score_batch(candidates, forecast)
        evals += len(candidates)
        beam = self._top_b(scored, cfg.beam_width)
        history.append(beam[0][2])
        if on_level is not None:
            on_level(0, evals, beam[0][2])

        # half the coarse spacing per dim, halved again each refine level
        step = np.array(
            [
                (self.space.sat.ub - self.space.sat.lb) / (cfg.grid - 1),
                (self.space.flow.ub - self.space.flow.lb) / (cfg.grid - 1),
                (self.space.chwst.ub - self.space.chwst.lb) / (cfg.grid - 1),
            ]
        ) / 2.0

        # ---- Refine levels ----
        for _ in range(cfg.levels):
            if evals >= cfg.max_evals:
                break
            neigh: list[Setpoints] = []
            for s, _kpi, _sc in beam:
                neigh.extend(self._neighborhood(s, step, cfg.neighbors))
            neigh = neigh[: cfg.max_evals - evals]
            if not neigh:
                break
            scored_n = self._score_batch(neigh, forecast)
            evals += len(neigh)

            prev_best = beam[0][2]
            beam = self._top_b(beam + scored_n, cfg.beam_width)
            new_best = beam[0][2]
            history.append(new_best)
            if on_level is not None:
                on_level(len(history) - 1, evals, new_best)
            step = step / 2.0

            if prev_best != INFEASIBLE and abs(prev_best - new_best) < cfg.epsilon * max(abs(prev_best), 1.0):
                break

        best_s, best_kpi, best_sc = beam[0]
        feasible = best_sc != INFEASIBLE
        return PlanResult(best_s, best_kpi, best_sc, evals, feasible, history)

    def _score_batch(self, candidates: Sequence[Setpoints], forecast) -> list[_Scored]:
        kpis = self.evaluator.evaluate(candidates, forecast)
        return [(c, k, score(k, self.weights)) for c, k in zip(candidates, kpis)]

    @staticmethod
    def _top_b(scored: list[_Scored], b: int) -> list[_Scored]:
        # stable sort by score; +inf (infeasible) sinks to the bottom
        return sorted(scored, key=lambda t: t[2])[:b]

    def _neighborhood(self, s: Setpoints, step: np.ndarray, n: int) -> list[Setpoints]:
        base = np.array(s.as_tuple())
        offsets = [
            np.array([step[0], 0.0, 0.0]),
            np.array([-step[0], 0.0, 0.0]),
            np.array([0.0, step[1], 0.0]),
            np.array([0.0, -step[1], 0.0]),
            np.array([0.0, 0.0, step[2]]),
            np.array([0.0, 0.0, -step[2]]),
            np.array([step[0], step[1], 0.0]),
            np.array([-step[0], -step[1], 0.0]),
            np.array([step[0], 0.0, step[2]]),
            np.array([-step[0], 0.0, -step[2]]),
            np.array([0.0, step[1], step[2]]),
            np.array([0.0, -step[1], -step[2]]),
        ][:n]
        out: list[Setpoints] = []
        for off in offsets:
            p = base + off
            out.append(self.space.clip(Setpoints(float(p[0]), float(p[1]), float(p[2]))))
        return out
