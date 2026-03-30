from datetime import datetime

import docker
import numpy as np

from numpy import ndarray
from typing import Optional, Callable, List, Tuple, Union, Any, Dict
from pathlib import Path

from dctwin.data import Action

from dctwin.adapters import EplusCloudAdapter
from dctwin.utils import EplusCloudEnvConfig, ControlType
from dctwin.utils import config as cloud_env

from cloudtwin.manager import CloudManager

from .eplus_env import EPlusEnv


class EplusCloudEnv(EPlusEnv):
    def __init__(
        self,
        config: EplusCloudEnvConfig,
        reward_fn: Optional[Callable] = None,
        schedule_fn: Optional[Callable] = None,
        docker_client: docker.DockerClient = None,
        **kwargs,
    ) -> None:
        self.eplus_configs = config.eplus
        self.cloud_configs = config.cloud
        self._schedule_fn = schedule_fn
        super().__init__(
            config=config.eplus,
            reward_fn=reward_fn,
            schedule_fn=schedule_fn,
            docker_client=docker_client,
            **kwargs,
        )
        self._set_cloud_environ()
        self._set_actions()
        # initialize cloud workloads management module
        self.cloud_backend = CloudManager(
            cloud_configs=config.cloud, building=self.building
        )
        # initialize the eplus-cloud co-simulation manager
        self.eplus_cloud_manager = EplusCloudAdapter(
            eplus_backend=self.eplus_backend, cloud_backend=self.cloud_backend
        )

    def _set_cloud_environ(self) -> None:
        """Set the environment variables for building-eplus co-simulation"""
        cloud_env.cloud.job_duration_estimator_config = (
            self.cloud_configs.job_duration_estimator_config
        )
        cloud_env.cloud.trace_file = Path(self.cloud_configs.trace_file)
        cloud_env.cloud.time_step = self.cloud_configs.time_step
        cloud_env.cloud.total_time_steps = self.cloud_configs.total_time_steps
        cloud_env.cloud.schedule_policy = self.cloud_configs.schedule_policy

    def _set_actions(self):
        """
        Adding actions for the cloud simulator to the action space
        """
        eplus_action_configs = [ac for ac in self.eplus_configs.actions]
        cloud_action_configs = [ac for ac in self.cloud_configs.actions]
        action_configs = cloud_action_configs + eplus_action_configs
        self._actions = [Action(config=ac) for ac in action_configs]
        self._use_unnormed_act = self._config.use_unnormed_act
        self.action_space = self._get_space(
            source=self._actions,
            use_unnormed_value=self._use_unnormed_act,
            count_criteria=lambda a: a.control_type == ControlType.AGENT_CONTROLLED,
            debug_tag="action",
        )

    def _restart_simulation(self) -> Tuple[ndarray, Any]:
        """Restart the simulation"""
        obs, done = self.eplus_cloud_manager.run(self.episode_idx)
        return obs, done

    def _get_actions_to_sent(self) -> Union[List[float], Dict]:
        """Reformat the actions to be sent to the simulator"""
        capacity_budget = self.inspect_action_by_name(
            action_name="capacity budget imdc level 2 cluster", use_unnormed=True
        )
        eplus_actions = [
            self.inspect_action_by_name(
                action_name=act.variable_name, use_unnormed=True
            )
            for act in self.actions
            if act.variable_name != "capacity budget imdc level 2 cluster"
        ]
        actions = {"capacity budget": capacity_budget, "eplus actions": eplus_actions}
        return actions

    def _run_simulation(
        self, parsed_actions: np.ndarray | List[float] | Dict
    ) -> Tuple[Union[List[float], None], bool]:
        self.eplus_cloud_manager.send_action(
            capacity_budget=parsed_actions["capacity budget"],
            eplus_actions=parsed_actions["eplus actions"],
        )
        obs, done = self.eplus_cloud_manager.receive_status()
        return obs, done

    def _get_additional_info_to_return(self):
        return dict(
            eplus_time=self.eplus_backend.current_time,
            time=self._timestamp if hasattr(self, "_timestamp") else datetime.now(),
            task_id=self._task_id,
        )

    @property
    def format_obs(self) -> dict:
        data = {}
        # format acu related observations
        for acu_name, acu in self.device_key_mapping["acus"].items():
            data[acu["fan"]["air mass flow rate"]] = self.inspect_current_observation(
                observation_name=f"{acu_name.lower()} fan air mass flow rate",
                use_unnormed=True,
            )
            data[acu["fan"]["power"]] = self.inspect_current_observation(
                observation_name=f"{acu_name.lower()} fan power consumption",
                use_unnormed=True,
            )
            data[acu["cooling coil"]["inlet air temperature"]] = (
                self.inspect_current_observation(
                    observation_name=f"{acu_name.lower()} cooling coil inlet air temperature",
                    use_unnormed=True,
                )
            )
            data[acu["cooling coil"]["air mass flow rate"]] = (
                self.inspect_current_observation(
                    observation_name=f"{acu_name.lower()} cooling coil air mass flow rate",
                    use_unnormed=True,
                )
            )
            data[acu["cooling coil"]["outlet air temperature"]] = (
                self.inspect_current_observation(
                    observation_name=f"{acu_name.lower()} cooling coil outlet air temperature",
                    use_unnormed=True,
                )
            )
            data[acu["cooling coil"]["inlet water temperature"]] = (
                self.inspect_current_observation(
                    observation_name=f"{acu_name.lower()} cooling coil inlet water temperature",
                    use_unnormed=True,
                )
            )
            data[acu["cooling coil"]["water mass flow rate"]] = (
                self.inspect_current_observation(
                    observation_name=f"{acu_name.lower()} cooling coil water mass flow rate",
                    use_unnormed=True,
                )
            )
        # format chilled water pump related observations
        for pump_name, pump in self.device_key_mapping["chilled water pumps"].items():
            data[pump["mass flow rate"]] = self.inspect_current_observation(
                observation_name=f"{pump_name.lower()} mass flow rate",
                use_unnormed=True,
            )
            data[pump["power"]] = self.inspect_current_observation(
                observation_name=f"{pump_name.lower()} power consumption",
                use_unnormed=True,
            )
        # format chiller related observations
        for chiller_name, chiller in self.device_key_mapping["chillers"].items():
            data[chiller["cooling load"]] = self.inspect_current_observation(
                observation_name=f"{chiller_name.lower()} cooling load",
                use_unnormed=True,
            )
            data[chiller["chilled water supply temperature"]] = (
                self.inspect_current_observation(
                    observation_name=f"{chiller_name.lower()} chilled water supply temperature",
                    use_unnormed=True,
                )
            )
            data[chiller["condenser water supply temperature"]] = (
                self.inspect_current_observation(
                    observation_name=f"{chiller_name.lower()} condenser water supply temperature",
                    use_unnormed=True,
                )
            )
            data[chiller["power"]] = self.inspect_current_observation(
                observation_name=f"{chiller_name.lower()} power consumption",
                use_unnormed=True,
            )
        # format condenser water pump related observations
        for pump_name, pump in self.device_key_mapping["condenser water pumps"].items():
            data[pump["mass flow rate"]] = self.inspect_current_observation(
                observation_name=f"{pump_name.lower()} mass flow rate",
                use_unnormed=True,
            )
            data[pump["power"]] = self.inspect_current_observation(
                observation_name=f"{pump_name.lower()} power consumption",
                use_unnormed=True,
            )
        # format cooling tower related observations
        for tower_name, tower in self.device_key_mapping["cooling towers"].items():
            data[tower["return water temperature"]] = self.inspect_current_observation(
                observation_name=f"{tower_name.lower()} return water temperature",
                use_unnormed=True,
            )
            data[tower["water mass flow rate"]] = self.inspect_current_observation(
                observation_name=f"{tower_name.lower()} water mass flow rate",
                use_unnormed=True,
            )
            data[tower["supply water temperature"]] = self.inspect_current_observation(
                observation_name=f"{tower_name.lower()} supply water temperature",
                use_unnormed=True,
            )
            data[tower["cooling tower air flow rate ratio"]] = (
                self.inspect_current_observation(
                    observation_name=f"{tower_name.lower()} air flow rate ratio",
                    use_unnormed=True,
                )
            )
            data[tower["outside air wetbulb temperature"]] = (
                self.inspect_current_observation(
                    observation_name="site outdoor air wetbulb temperature",
                    use_unnormed=True,
                )
            )
            data[tower["power"]] = self.inspect_current_observation(
                observation_name=f"{tower_name.lower()} fan power consumption",
                use_unnormed=True,
            )
        # format electric load center related observations
        for center_name, center in self.device_key_mapping[
            "electrical load centers"
        ].items():
            data[center["produced electricity"]] = self.inspect_current_observation(
                observation_name=f"{center_name.lower()} produced electricity",
                use_unnormed=True,
            )
        # format environment related observations
        data["outdoor air drybulb temperature"] = self.inspect_current_observation(
            observation_name="site outdoor air drybulb temperature", use_unnormed=True
        )
        data["outdoor air wetbulb temperature"] = self.inspect_current_observation(
            observation_name="site outdoor air wetbulb temperature", use_unnormed=True
        )
        data["wind speed"] = self.inspect_current_observation(
            observation_name="site wind speed", use_unnormed=True
        )
        data["diffuse solar radiation rate per area"] = (
            self.inspect_current_observation(
                observation_name="site diffuse solar radiation rate per area",
            )
        )
        data["direct solar radiation rate per area"] = self.inspect_current_observation(
            observation_name="site direct solar radiation rate per area",
        )
        data["ground reflected solar radiation rate per area"] = (
            self.inspect_current_observation(
                observation_name="site ground reflected solar radiation rate per area",
            )
        )
        return data

    def step(self, raw_actions: np.ndarray):
        # use user-defined callback function to get the customized IT-side schedules and augment the raw actions from
        # the agent to get the complete action
        raw_actions = self._schedule_fn(self, raw_actions)
        self._prepare_actions(raw_actions)
        self.last_obs = self._get_observations_to_return(use_unnormed_obs=True)
        raw_obs, done = self._run_simulation(self._get_actions_to_sent())
        if self._use_simulation_time:
            self._timestamp += self._timestamp_interval
        self._prepare_observations(raw_obs)
        return (
            self._get_observations_to_return(),
            self._calculate_reward(),
            done,
            False,
            self._get_additional_info_to_return(),
        )
