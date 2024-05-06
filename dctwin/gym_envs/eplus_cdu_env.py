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

from dclib.building import Building
from dctwin.adapters import EplusLiquidAdapter
from dctwin.utils import CDUEnvConfig

from .eplus_env import EPlusEnv
from .ds import Observation, Action, ActionControlType


class EplusCDUEnv(EPlusEnv):
    """The environment class for co-simulation of liquid cooling CDUs inside data halls and the chiller plant.
    """

    def __init__(
        self,
        config: CDUEnvConfig,
        building: Building,
        map_cdu_inputs_fn: Callable,
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
        self.cdu_config = config.cdu
        self.eplus_config = config.eplus
        # self._set_eplus_cfd_environ()
        self.eplus_cdu_manager = EplusLiquidAdapter(
            building=building,
            eplus_backend=self.eplus_backend,
            map_cdu_inputs_fn=map_cdu_inputs_fn
        )
        # more additional observation can be added if more simulators are introduced in the future
        self._set_cdu_observations()
        self._set_cdu_actions()

    def _set_cdu_observations(self) -> None:
        """Append the observations for co-simulation of CDUs and E+"""
        self._observations += [
            Observation(config=oc) for oc in self.cdu_config.observations
        ]
        self._use_unnormed_obs = self.cdu_config.use_unnormed_obs
        self.observation_space = self._get_space(
            self._observations,
            self._use_unnormed_obs,
            lambda o: o.exposed,
            debug_tag="observation",
        )

    def _set_cdu_actions(self) -> None:
        """Append the actions for co-simulation of CDUs and E+"""
        self._use_unnormed_act = self.cdu_config.use_unnormed_act
        self._actions += [
            Action(config=ac) for ac in self.cdu_config.actions
        ]
        self.action_space = self._get_space(
            source=self._actions,
            use_unnormed_value=self._use_unnormed_act,
            count_criteria=lambda a: a.control_type
            == ActionControlType.AGENT_CONTROLLED,
            debug_tag="action",
        )

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
        obs, done = self.eplus_cdu_manager.run(self.episode_idx)
        return obs, done

    def _run_simulation(
        self, parsed_actions: Dict
    ) -> Tuple[Union[List[float], None], bool]:
        self.eplus_cdu_manager.send_action(
            parsed_actions, 
            num_eplus_actions=len(self.eplus_config.actions),
        )
        obs, done = self.eplus_cdu_manager.receive_status()
        return obs, done
