from gym.envs.registration import register
from loguru import logger


from .gym_env import BaseEnv
from .gym_env import EPlusEnv
from .gym_env import CoSimEnv

from .singleton import CFDManager, CoSimManager, PODBuilder


registry = dict(
    eplus_env_config=('EplusEnv-v0', 'dctwin.interfaces.gym_env.eplus_env:EPlusEnv'),
    cosim_env_config=('CoSimEnv-v0', 'dctwin.interfaces.gym_env.cosim_env:CoSimEnv'),
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
    "CoSimEnv",
    "CFDManager",
    "CoSimManager",
    "PODBuilder",
]
