import gym
from typing import Union, Callable
from google.protobuf import json_format
from dctwin.utils import read_engine_config
from dctwin.gym_envs import get_env_id, BaseEnv
from dclib import Building

def make_env(
    env_proto_config: str,
    reward_fn: Callable[[BaseEnv], float],
    schedule_fn: Callable = None,
    parse_obs_fn: Callable = None,
    map_boundary_condition_fn: Callable = None,
    map_cdu_inputs_fn: Callable = None,
    building: Building = None,
    is_k8s: bool = False,
    k8s_config: dict = None,
) -> Union[gym.Env, BaseEnv]:
    """The factory function to create the environment.
    :param env_proto_config: the path to the protobuf config file
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
    :param schedule_fn: the callback facility workloads function defined by the user
    :param paarse_obs_fn: the callback function to parse the observations returned by the environment
    :param map_boundary_condition_fn: the callback function to map the boundary conditions
        defined by the user, this is only used for co-simulation
        e.g., the format of the boundary conditions should be consistent with the CFDManger
        input -> cpu_utilization, supply_air_temperatures, supply_air_volume_flow_rates
        output: boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
        }
    :param is_k8s: whether the environment is running in k8s
    return: the gym-like environment instance
    """
    engine_config = read_engine_config(env_proto_config)
    env_config_name = engine_config.WhichOneof("EnvConfig")
    env_params = json_format.MessageToDict(
        getattr(engine_config, env_config_name).env_params,
        preserving_proto_field_name=True,
    )
    if env_config_name == "eplus_cfd_env_config":
        env_params.update({"map_boundary_condition_fn": map_boundary_condition_fn})
    if env_config_name == "eplus_cdu_env_config":
        env_params.update({"map_cdu_inputs_fn": map_cdu_inputs_fn})
        env_params.update({"building": building})
    env = gym.make(
        get_env_id(env_config_name),
        config=getattr(engine_config, env_config_name),
        reward_fn=reward_fn,
        schedule_fn=schedule_fn,
        parse_obs_fn=parse_obs_fn,
        is_k8s=is_k8s,
        k8s_config=k8s_config,
        **env_params
    )

    return env
