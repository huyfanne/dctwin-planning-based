import docker
from numpy import ndarray
from typing import (
    Optional,
    Callable,
    List,
    Tuple,
    Union,
    Any,
    Dict,
)

from pathlib import Path
from dctwin.adapters import EplusCFDAdapter
from dctwin.utils import CoSimEnvConfig
from dctwin.utils import config as cosim_env
from dctwin.models import Room

from .eplus_env import EPlusEnv
from .ds import Observation


class CoSimEnv(EPlusEnv):
    """The environment class for co-simulation of data hall and chiller plant.

    :param config: the config of the engine from protobuf
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
        Why? we tried to use a templated function with params, but turns out it's bad
    :param schedule_fn: the callback facility schedule function defined by the user
        e.g., the IT utilization schedule
    """

    def __init__(
        self,
        config: CoSimEnvConfig,
        map_boundary_condition_fn: Callable,
        reward_fn: Optional[Callable] = None,
        schedule_fn: Optional[Callable] = None,
        docker_client: docker.DockerClient = None,
        **kwargs,
    ) -> None:
        super().__init__(
            config=config.eplus,
            reward_fn=reward_fn,
            schedule_fn=schedule_fn,
            docker_client=docker_client,
            **kwargs,
        )
        cosim_env.co_sim.idf2room_map = Path(config.idf2room_map)
        self.cfd_config = config.cfd
        self._set_cosim_environ()
        self.co_sim_manager = EplusCFDAdapter(
            room=Room.load(cosim_env.cfd.geometry_file),
            write_interval=config.cfd.write_interval,
            end_time=config.cfd.end_time,
            field_config=config.cfd.field_config,
            mesh_process=config.cfd.process_num,
            solve_process=config.cfd.process_num,
            steady=config.cfd.steady,
            run_cfd=config.cfd.run_cfd,
            pod_method=config.cfd.pod_method,
            docker_client=docker_client,
            eplus_backend=self.eplus_backend,
            map_boundary_condition_fn=map_boundary_condition_fn,
        )
        # more additional observation can be added if more simulators are introduced in the future
        self._set_cfd_observations()

    def _set_cfd_observations(self) -> None:
        """Append the observations for co-simulation
        Note: there are no external observations for CFD simulation
        """
        self._observations += [
            Observation(config=oc) for oc in self.cfd_config.observations
        ]
        self._use_unnormed_obs = self.cfd_config.use_unnormed_obs
        self.observation_space = self._get_space(
            self._observations,
            self._use_unnormed_obs,
            lambda o: o.exposed,
            debug_tag="observation",
        )

    def _set_cosim_environ(self) -> None:
        """Set the environment variables for co-simulation"""
        cosim_env.cfd.geometry_file = Path(self.cfd_config.geometry_file)
        cosim_env.cfd.pod_dir = Path(self.cfd_config.pod_dir)
        cosim_env.cfd.mesh_dir = Path(self.cfd_config.mesh_dir)
        cosim_env.cfd.object_mesh_index = Path(self.cfd_config.object_mesh_index)
        cosim_env.cfd.dry_run = self.cfd_config.dry_run

    def _get_actions_to_sent(self) -> Dict[str, List]:
        """
        Transfer raw action array into a dict specified with the format of
        "action_name: action_value". Action names are specified in the proto configuration
        """
        action_dict = {}
        for action in self._actions:
            value = self.inspect_action_by_name(action.variable_name)
            action_dict[action.variable_name] = value
        return action_dict

    def _restart_simulation(self) -> Tuple[ndarray, Any]:
        obs, done = self.co_sim_manager.run(self.episode_idx)
        return obs, done

    def _run_simulation(
        self, parsed_actions: Dict
    ) -> Tuple[Union[List[float], None], bool]:
        self.co_sim_manager.send_action(parsed_actions)
        obs, done = self.co_sim_manager.receive_status()
        return obs, done
