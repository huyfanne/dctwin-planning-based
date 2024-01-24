from datetime import datetime, timedelta
from typing import Callable, List, Any, Union, Tuple, Dict, Optional

import gym
from gym.utils import seeding
import numpy as np
from loguru import logger

from dctwin.utils import (
    DTEngineConfig,
    ScalarDataItemConfig,
    config as base_env,
)

from .ds import (
    ScalarDataItem,
    Action,
    Observation,
    Reward,
    ActionControlType,
)


class BaseEnv(gym.Env):
    """Base class for all data center environments.

    :param EngineConfig config: the config of the engine from protobuf
    :param reward_fn: the callback reward function defined by the user
        We need the user to pass in a reward function
        Why? we tried to use a templated function with params, but turns out it's bad
    :param schedule_fn: the callback facility schedule function defined by the user
        e.g., the IT utilization schedule
    :param task_id: the identity of the current environment (defined for multi-task learning)
    :param num_constraints: the number of constraints in the environment (defined 0)
    """

    def __init__(
        self,
        config: DTEngineConfig,
        reward_fn: Callable,
        schedule_fn: Callable,
        task_id: Optional[str] = "0",
        num_constraints: Optional[int] = 0,
        last_episode_idx: Optional[int] = None,
    ) -> None:
        super().__init__()
        # set up basics
        self._precision = np.float64
        self._config = config

        # Set up actions
        self._schedule_fn = schedule_fn
        self._set_actions()

        # set up observations
        self._set_observations()

        # set up reward
        self._reward = Reward(ScalarDataItemConfig(variable_name="reward"))
        self._reward_fn = reward_fn

        # set up simulation time
        self._set_simulation_time()

        # others
        self.last_obs = None
        if last_episode_idx is not None:
            self.episode_idx = last_episode_idx
        else:
            self.episode_idx = 0
        self._task_id = task_id
        self._num_constraints = num_constraints
        self._timestamp: datetime = datetime.now()

    def _set_observations(self):
        self._observations = [
            Observation(config=oc) for oc in self._config.observations
        ]
        self._num_external_observations = 0
        for o in self._observations:
            if o.type == "EXTERNAL":
                self._num_external_observations += 1
        self._use_unnormed_obs = self._config.use_unnormed_obs
        self.observation_space = self._get_space(
            source=self._observations,
            use_unnormed_value=self._use_unnormed_obs,
            count_criteria=lambda o_: o_.exposed,
            debug_tag="observation",
        )
        self.last_obs = None

    def _set_actions(self) -> None:
        self._actions = [Action(config=ac) for ac in self._config.actions]
        self._use_unnormed_act = self._config.use_unnormed_act
        self.action_space = self._get_space(
            source=self._actions,
            use_unnormed_value=self._use_unnormed_act,
            count_criteria=lambda a: a.control_type
            == ActionControlType.AGENT_CONTROLLED,
            debug_tag="action",
        )
        if any(
            map(lambda a: a.control_type == ActionControlType.CUSTOMIZED, self._actions)
        ):
            if self._schedule_fn is None:
                logger.critical(
                    "Env contains CUSTOMIZED action but no schedule_fn was specified!"
                )
                exit(-1)

    def _set_simulation_time(self) -> None:
        if self._config.HasField("simulation_time_config"):
            logger.info("Using pre-set simulation time")
            begin_month = self._config.simulation_time_config.begin_month
            begin_day_of_month = self._config.simulation_time_config.begin_day_of_month
            year = datetime.now().year
            self._starting_timestamp = datetime(
                year=year, month=begin_month, day=begin_day_of_month
            )
            self._timestamp_interval = timedelta(
                minutes=int(
                    60
                    / self._config.simulation_time_config.number_of_timesteps_per_hour
                )
            )
            self._timestamp = self._starting_timestamp
            base_env.co_sim.timestamp = self._timestamp
            self._use_simulation_time = True
        else:
            logger.info("Using real-world time")
            self._use_simulation_time = False

    @property
    def actions(self):
        return self._actions

    @property
    def observations(self):
        return self._observations

    @property
    def num_constraints(self):
        if self._num_constraints == 0:
            raise NotImplementedError(
                "environment constraints are not defined! "
                "Please specify the number of constraints in the environment."
            )
        else:
            return self._num_constraints

    def _get_space(
        self,
        source: List,
        use_unnormed_value: bool,
        count_criteria: Callable,
        debug_tag: str,
    ) -> gym.spaces.Box:
        min_, max_ = np.finfo(self._precision).min, np.finfo(self._precision).max
        lb_, ub_ = [], []
        if len(source) == 0:
            logger.warning(f"The env has no {debug_tag} specified!")
        for item in source:
            if not count_criteria(item):
                continue
            if use_unnormed_value:
                lb_.append(item.resizer.lb)
                ub_.append(item.resizer.ub)
            else:
                lb_.append(
                    item.resizer.resized_lb if item.resizer is not None else min_
                )
                ub_.append(
                    item.resizer.resized_ub if item.resizer is not None else max_
                )
        space = gym.spaces.Box(
            low=np.array(lb_, dtype=self._precision),
            high=np.array(ub_, dtype=self._precision),
            dtype=self._precision,
        )
        if space.shape[0] == 0:
            logger.warning(f"The env has no {debug_tag} exposed to the agent!")
        return space

    @staticmethod
    def _find_scalar_item(
        source: List[ScalarDataItem], name: str
    ) -> Union[None, Action, Observation]:
        return next((s for s in source if s.variable_name == name), None)

    @staticmethod
    def _get_scalar_values(
        source: List[ScalarDataItem], use_unnormed: bool
    ) -> Union[list, float, int]:
        return [
            d.get_unnormed_value() if use_unnormed else d.get_normed_value()
            for d in source
        ]

    def _get_value_to_set(self, v, ptr, source) -> Tuple[int, Any]:
        if v.type != "EXTERNAL":
            value_to_set = source[ptr]
            ptr += 1
        else:
            tmp = self._find_scalar_item(self._actions, v.variable_name)
            assert tmp is not None, ""
            value_to_set = tmp.peek()
        return ptr, value_to_set

    def _set_scalar_items(
        self,
        source: Union[np.ndarray, List],
        target: Union[List[Observation], List[Action]],
        is_source_unnormed: bool,
    ) -> None:
        ptr = 0
        for v in target:
            if type(v) == Observation:
                ptr, value_to_set = self._get_value_to_set(v, ptr, source)
                if is_source_unnormed:
                    v.set_unnormed_value(value_to_set)
                else:
                    v.set_normed_value(value_to_set)
            else:
                if is_source_unnormed:
                    v.set_unnormed_value(source[ptr])
                else:
                    v.set_normed_value(source[ptr])
                ptr += 1

    def _prepare_actions(self, raw_action) -> None:
        complete_raw_action = []
        ra_ptr = 0
        for a in self._actions:
            if a.control_type == ActionControlType.FIXED:
                value = a.default_value
            elif a.control_type == ActionControlType.AGENT_CONTROLLED:
                if ra_ptr >= len(raw_action):
                    logger.critical(
                        "Insufficient agent-controlled actions are provided!"
                    )
                    exit(-1)
                value = raw_action[ra_ptr]
                ra_ptr += 1
            elif (
                a.control_type == ActionControlType.PRE_SCHEDULED
                or a.control_type == ActionControlType.ACTUATOR_PRE_SCHEDULED
            ):
                value = next(a)
            elif a.control_type == ActionControlType.CUSTOMIZED:
                value = self._schedule_fn(
                    a.variable_name, **self._get_customized_schedule_context()
                )
            else:
                logger.critical(f"Unknown type of action! {a.control_type}")
                exit(-1)
            complete_raw_action.append(value)
        if ra_ptr != len(raw_action):
            logger.warning(
                "More agent-controlled actions than specified are provided! Ignoring the rest..."
            )
        self._set_scalar_items(
            complete_raw_action, self._actions, self._use_unnormed_act
        )

    def _prepare_observations(self, raw_observation) -> None:
        # received obs is always unnormed in our case
        self._set_scalar_items(
            raw_observation, self._observations, is_source_unnormed=True
        )

    def _get_actions_to_sent(self) -> Union[List[float], Dict]:
        return self._get_scalar_values(self._actions, use_unnormed=True)

    def _get_observations_to_return(self, use_unnormed_obs: bool = False) -> np.ndarray:
        visible_obs = []
        for o in self._observations:
            if not o.exposed:
                continue
            if use_unnormed_obs:
                visible_obs.append(o.get_unnormed_value())
            else:
                visible_obs.append(o.get_normed_value())
        return np.asarray(visible_obs)

    def _get_additional_info_to_return(self):
        return dict(
            time=self._timestamp if hasattr(self, "_timestamp") else datetime.now(),
            task_id=self._task_id,
        )

    def _calculate_reward(self) -> float:
        if self._reward_fn is None:
            return 0.0
        self._reward.set_unnormed_value(
            self._reward_fn(
                self,  # the observation can be inspected by calling the class inspect methods
            )
        )
        return self._reward.get_unnormed_value()

    def _get_customized_schedule_context(self) -> dict:
        """
        get env status that could be used for the customer schedule function to work in dict form
        for example:
        {
            episode: self.episode,
            timestamp: xxx,
            current_observation: xx,
            ....
        }
        it may includes a lots of info that is logically unknown to the agent
        :return:
        """
        raise NotImplementedError

    def _run_simulation(
        self, parsed_actions: Union[List[float], Dict]
    ) -> Tuple[Union[List[float], None], bool]:
        """send action, receive obs and if done"""
        raise NotImplementedError

    def _restart_simulation(self) -> List[float]:
        """restart and returns a raw observation"""
        raise NotImplementedError

    def step(self, raw_action):
        """step function for the agent
        gym-like step function
        """
        self._prepare_actions(raw_action)
        self.last_obs = self._get_observations_to_return(use_unnormed_obs=True)
        raw_obs, done = self._run_simulation(self._get_actions_to_sent())
        self._prepare_observations(raw_obs)
        if self._use_simulation_time:
            self._timestamp += self._timestamp_interval

        return (
            self._get_observations_to_return(),
            self._calculate_reward(),
            done,
            False,
            self._get_additional_info_to_return(),
        )

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Union[np.ndarray, Tuple[np.ndarray, Dict]]:
        """reset the env and return the first observation
        gym-like reset function
        """
        if seed is not None:
            self._np_random, seed = seeding.np_random(seed)
        self.episode_idx += 1
        observations, done = self._restart_simulation()
        self._prepare_observations(observations)
        if self._use_simulation_time:
            self._timestamp = self._starting_timestamp
        return (
            self._get_observations_to_return(
                use_unnormed_obs=self._use_unnormed_obs,
            ),
            self._get_additional_info_to_return(),
        )

    def render(self, mode="human"):
        raise NotImplementedError

    def inspect_current_observation(
        self, observation_name: str = None, use_unnormed: bool = None
    ) -> Union[None, float, int, List[Union[float, int]]]:
        """
        Get current observation / status

        if observation_name is not specified, all observation values are returned (including the non-exposed ones)
        if the use_unnormed is not specified, it will follow the general observation space

        Q: Why use "inspect" not "get"?
        A: To highlight that its checks and returned non-exposed observations as well

        Q: Why are non-exposed observations accessible as well?
        A: It is for the convenience of development, accessing only the exposed ones to the agent is not
        sufficient

        Q: What if I only want to get those exposed to the agent?
        A: Since such requirement is agent-centric, you should keep track it after each step(...).
        """
        if use_unnormed is None:
            use_unnormed = self._use_unnormed_obs
        if observation_name is None:
            return self._get_scalar_values(self._observations, use_unnormed)
        else:
            o = self._find_scalar_item(self._observations, observation_name)
            if o is None:
                logger.error(f"Observation {observation_name} does not exist!")
                return None
            else:
                return self._get_scalar_values([o], use_unnormed)[0]

    def inspect_next_scheduled_action_value(
        self,
        action_name: str,
    ) -> Union[None, float, int]:
        """
        Q: Why don't we have a similar method just like "inspect_current_observation"?
        A: We don't think it is a common need to get the previous executed action.

        Q: The value returned by this method, is it normed or unnormed?
        A: Depending on the source. It is exact value read from the source pickle.

        Q: Why don't we get all next scheduled action?
        A: The indexing could be confusing and such requirement is not common.
        """
        a = self._find_scalar_item(self._actions, action_name)
        if a is None:
            logger.error(f"Action {action_name} does not exist!")
        elif a.control_type != ActionControlType.PRE_SCHEDULED:
            logger.error(
                f"Action {action_name} is not PRE_SCHEDULED, cannot get its next scheduled value!"
            )
        else:
            return a.peek()

    def inspect_action_by_name(self, action_name: str):
        a = self._find_scalar_item(self._actions, action_name)
        return a.get_unnormed_value()

    def get_normed_obs_by_name(
        self,
        variable_name: str = None,
        unnormed_value: float = None,
    ) -> Union[None, float]:
        o = self._find_scalar_item(self._observations, variable_name)
        if o is None:
            logger.error(f"{variable_name} does not exist!")
            return None
        else:
            o.set_unnormed_value(unnormed_value)
            normed_obs = o.get_normed_value()
            return normed_obs

    def get_unnormed_obs_by_name(
        self,
        variable_name: str = None,
        normed_value: float = None,
    ) -> Union[None, float]:
        o = self._find_scalar_item(self._observations, variable_name)
        if o is None:
            logger.error(f"{variable_name} does not exist!")
            return None
        else:
            o.set_normed_value(normed_value)
            normed_obs = o.get_unnormed_value()
            return normed_obs

    def get_unnormed_act_by_name(
        self,
        variable_name: str = None,
        normed_value: float = None,
    ) -> Union[None, float]:
        a = self._find_scalar_item(self._actions, variable_name)
        if a is None:
            logger.error(f"{variable_name} does not exist!")
            return None
        else:
            a.set_normed_value(normed_value)
            unnormed_act = a.get_unnormed_value()
            return unnormed_act

    def get_normed_act_by_name(
        self,
        variable_name: str = None,
        unnormed_value: float = None,
    ) -> Union[None, float]:
        a = self._find_scalar_item(self._actions, variable_name)
        if a is None:
            logger.error(f"{variable_name} does not exist!")
            return None
        else:
            a.set_unnormed_value(unnormed_value)
            normed_act = a.get_normed_value()
            return normed_act
