from __future__ import annotations

import argparse

import dctwin
from dcwiz_policy_template import TrajectoryPolicyTemplate

from planner.env_actions import mapper_from_env
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


class BaselineTrajectory(TrajectoryPolicyTemplate):
    """Conservative baseline: coolest SAT/CHW, maximum airflow (safe, energy-heavy)."""

    def initialize(self, *args, **kwargs):
        dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        self.env = dctwin.make_env(env_proto_config=dt_engine_config, reward_fn=lambda x: 0)
        s = DEFAULT_SEARCH_SPACE
        baseline = Setpoints(sat_c=s.sat.lb, flow_kg_s=s.flow.ub, chwst_c=s.chwst.lb)
        self.act = mapper_from_env(self.env).expand(baseline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the conservative baseline trajectory")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    args = parser.parse_args()
    BaselineTrajectory()(policy="baseline", dt_engine_config=args.dt)
    print("Baseline trajectory complete")
