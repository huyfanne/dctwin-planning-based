import numpy as np

from dctwin.interfaces.gym_envs import CoSimEnv
from dctwin.utils import config as env_config
from dctwin.utils import read_engine_config, setup_logging
from hooks import map_boundary_condition_fn
from google.protobuf import json_format


engine_config = "configs/test_cosim.prototxt"
env_config.eplus.engine_config_file = engine_config

config = read_engine_config(engine_config=engine_config)
setup_logging(config.logging_config, engine_config=engine_config)

env_config_name = config.WhichOneof("EnvConfig")
env_params = json_format.MessageToDict(
    getattr(config, env_config_name).env_params,
    preserving_proto_field_name=True,
)
env = CoSimEnv(
    config=getattr(config, env_config_name),
    reward_fn=None,
    schedule_fn=None,
    map_boundary_condition_fn=map_boundary_condition_fn,
    **env_params,
)

# start the first CFD simulation
env.reset()

# run simulation with eplus only
action_dict = {"ACU1_setpoint": 18.0, "ACU1_flow_rate": 15.0, "chw_supply_sp": 7.0}
act = np.array(
    [
        action_dict["ACU1_setpoint"],
        action_dict["ACU1_flow_rate"],
        action_dict["chw_supply_sp"],
    ]
)
done = False
env_config.cfd.dry_run = True
env_config.cfd.mesh_dir = env_config.LOG_DIR.joinpath("base")
while not done:
    obs, rew, done, truncated, info = env.step(act)
