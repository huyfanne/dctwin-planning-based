import gym
from typing import Union, Callable
from google.protobuf import json_format
from dctwin.utils import read_engine_config
from dctwin.interfaces import get_env_id, BaseEnv


def make_env(
    env_proto_config: str,
    reward_fn: Callable[[BaseEnv], float],
    schedule_fn: Callable = None,
) -> Union[gym.Env, BaseEnv]:
    """The factory function to create the environment.
    :param env_proto_config: the path to the protobuf config file
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
    :param schedule_fn: the callback facility schedule function defined by the user

    return: the gym-like environment instance
    """
    engine_config = read_engine_config(env_proto_config)
    env_config_name = engine_config.WhichOneof("EnvConfig")
    env_params = json_format.MessageToDict(
        getattr(engine_config, env_config_name).env_params,
        preserving_proto_field_name=True,
    )
    env = gym.make(
        get_env_id(env_config_name),
        config=getattr(engine_config, env_config_name),
        reward_fn=reward_fn,
        schedule_fn=schedule_fn,
        **env_params
    )

    return env
