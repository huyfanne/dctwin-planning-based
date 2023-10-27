import gym
from typing import Union, Callable
from google.protobuf import json_format
from dctwin.utils import read_engine_config
from dctwin.interfaces import get_env_id, BaseEnv


def make_env(
    env_proto_config: str,
    reward_fn: Callable[[BaseEnv], float],
    schedule_fn: Callable = None,
    map_boundary_condition_fn: Callable = None,
    is_k8s: bool = False,
) -> Union[gym.Env, BaseEnv]:
    """The factory function to create the environment.
    :param env_proto_config: the path to the protobuf config file
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
    :param schedule_fn: the callback facility schedule function defined by the user
    :param map_boundary_condition_fn: the callback function to map the boundary conditions
        defined by the user, this is only used for co-simulation
        e.g., the format of the boundary conditions should be consistent with the CFDManger
        input -> cpu_utilization, supply_air_temperatures, supply_air_volume_flow_rates
        output: boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
        }
    return: the gym-like environment instance
    """
    engine_config = read_engine_config(env_proto_config)
    env_config_name = engine_config.WhichOneof("EnvConfig")
    env_params = json_format.MessageToDict(
        getattr(engine_config, env_config_name).env_params,
        preserving_proto_field_name=True,
    )
    if env_config_name == "cosim_env_config":
        env_params.update({"map_boundary_condition_fn": map_boundary_condition_fn})
    env = gym.make(
        get_env_id(env_config_name),
        config=getattr(engine_config, env_config_name),
        reward_fn=reward_fn,
        schedule_fn=schedule_fn,
        is_k8s=is_k8s,
        **env_params
    )

    return env
