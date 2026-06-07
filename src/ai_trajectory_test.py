from __future__ import annotations

import argparse
import json
from pathlib import Path

import dctwin
from dcwiz_policy_template import TrajectoryPolicyTemplate

from planner.env_actions import mapper_from_env
from planner.types import Setpoints


class AITrajectoryReplay(TrajectoryPolicyTemplate):
    """Replay the recommended weekly setpoints (held constant) over the full week."""

    def initialize(self, *args, **kwargs):
        dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        recommendation = kwargs.get("recommendation", "log/recommendation.json")
        self.env = dctwin.make_env(env_proto_config=dt_engine_config, reward_fn=lambda x: 0)

        rec = json.loads(Path(recommendation).read_text())["setpoints"]
        setpoints = Setpoints(
            sat_c=rec["crah_supply_air_temperature_c"],
            flow_kg_s=rec["crah_supply_air_mass_flow_rate_kg_s"],
            chwst_c=rec["chilled_water_supply_temperature_c"],
        )
        self.act = mapper_from_env(self.env).expand(setpoints)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay recommended setpoints (pre-validation)")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--recommendation", default="log/recommendation.json")
    args = parser.parse_args()
    AITrajectoryReplay()(policy="ai", dt_engine_config=args.dt,
                         recommendation=args.recommendation)
    print("AI trajectory replay complete")
