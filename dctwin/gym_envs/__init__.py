"""
This module contains the standard gym interfaces for AI interaction
Please refer the gym interface at:

    https://github.com/openai/gym
"""

from .base_env import BaseEnv
from .eplus_env import EPlusEnv
from .eplus_cfd_env import EplusCFDEnv

from gym.envs.registration import register
from loguru import logger


registry = dict(
    eplus_env_config=("EplusEnv-v0", "dctwin.gym_envs.eplus_env:EPlusEnv"),
    eplus_cfd_env_config=(
        "EplusCFDEnv-v0",
        "dctwin.gym_envs.eplus_cfd_env:EplusCFDEnv",
    ),
    eplus_cdu_env_config=(
        "EplusCDUEnv-v0",
        "dctwin.gym_envs.eplus_cdu_env:EplusCDUEnv",
    ),
)

for env_id, entry_point in registry.values():
    register(
        id=env_id,
        entry_point=entry_point,
    )


def get_env_id(config_name):
    if config_name not in registry:
        logger.critical(
            f"Unexpected config name {config_name}! Corresponding env not registered!"
        )
    return registry[config_name][0]


__all__ = [
    "get_env_id",
    "BaseEnv",
    "EPlusEnv",
    "EplusCFDEnv",
]
