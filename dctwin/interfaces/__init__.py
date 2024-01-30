from gym.envs.registration import register
from loguru import logger

from .gym_envs import BaseEnv, EPlusEnv, EplusCFDEnv
from .managers import CFDManager, PODBuilder


registry = dict(
<<<<<<< HEAD
    eplus_env_config=('EplusEnv-v0', 'dctwin.interfaces.gym_envs.eplus_env:EPlusEnv'),
    eplus_cfd_env_config=('EplusCFDEnv-v0', 'dctwin.interfaces.gym_envs.eplus_cfd_env:EplusCFDEnv'),
=======
    eplus_env_config=("EplusEnv-v0", "dctwin.interfaces.gym_envs.eplus_env:EPlusEnv"),
    cosim_env_config=("CoSimEnv-v0", "dctwin.interfaces.gym_envs.cosim_env:CoSimEnv"),
>>>>>>> main
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
    "CFDManager",
    "PODBuilder",
]
