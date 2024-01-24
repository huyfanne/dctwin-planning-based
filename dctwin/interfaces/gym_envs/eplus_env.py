import docker
from typing import (
    Callable,
    List,
    Tuple,
    Union,
    Optional,
)
from loguru import logger
from pathlib import Path
from dctwin.backends import EplusBackend, EplusBackendK8s
from dctwin.utils import config as eplus_env
from dctwin.utils import EPlusEnvConfig

from .base_env import BaseEnv


class EPlusEnv(BaseEnv):
    """The environment class for EnergyPlus.

    :param config: the config of the eplus engine from protobuf
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
        Why? we tried to use a templated function with params, but turns out it's bad
    :param schedule_fn: the callback facility schedule function defined by the user
        e.g., the IT utilization schedule
    """

    def __init__(
        self,
        config: EPlusEnvConfig,
        reward_fn: Optional[Callable] = None,
        schedule_fn: Optional[Callable] = None,
        docker_client: docker.DockerClient = None,
        is_k8s: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            config=config,
            reward_fn=reward_fn,
            schedule_fn=schedule_fn,
            **kwargs,
        )
        self._set_eplus_environ()
        if is_k8s:
            self.eplus_backend = EplusBackendK8s(
                proto_config=config,
                host=config.host,
                network=config.network,
                docker_client=docker_client,
            )
        else:
            self.eplus_backend = EplusBackend(
                proto_config=config,
                host=config.host,
                network=config.network,
                docker_client=docker_client,
            )

    def _set_eplus_environ(self) -> None:
        eplus_env.eplus.idf_file = Path(self._config.model_file)
        eplus_env.eplus.weather_file = Path(self._config.weather_file)

    def _get_customized_schedule_context(self) -> dict:
        return dict(
            episode=self.episode_idx,
        )

    def _restart_simulation(self) -> Tuple[Union[float, None], Union[float, None]]:
        obs, done = self.eplus_backend.run(self.episode_idx)
        return obs, done

    def _run_simulation(
        self, parsed_actions: List[float]
    ) -> Tuple[Union[List[float], None], bool]:
        self.eplus_backend.send_action(parsed_actions)
        return self.eplus_backend.receive_status()

    def render(self, mode="human"):
        logger.info("Rendering is not supported currently.")
