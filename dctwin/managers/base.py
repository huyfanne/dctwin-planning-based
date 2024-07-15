from abc import abstractmethod
from datetime import datetime, timedelta
from typing import Callable, List, Any, Union, Tuple, Dict, Optional

import gym
from dclib.cooling.plant.loops import Branch, CondenserWaterLoops, SecondaryChilledWaterLoops, ChilledWaterLoops
from gym.utils import seeding
import numpy as np
from loguru import logger
from torch import nn

from dctwin.utils import (
    DTEngineConfig,
    ScalarDataItemConfig,
    config as base_env,
)

from dctwin.managers.ds import (
    ScalarDataItem,
    Action,
    Observation,
    ActionControlVariable,
)

from dctwin.data.batch import Batch
from dclib import Building
from dclib.cooling.plant.facilities import Chiller, CoolingTower, Pump
import torch


class BaseManager(nn.Module):
    """ Base class for all data center environments.
    """

    def __init__(
        self,
        config: DTEngineConfig,
        building: Building,
    ) -> None:
        super().__init__()
        # set up basics
        self._config = config
        self._building = building

        # set up inputs
        # Set up actions
        self._set_actions()
        # set up observations
        self._set_observations()
        # reset observation and action data
        self._reset_data()

        # others
        self.last_obs = None
        self.acts_required_grad: torch.Tensor = torch.tensor([], requires_grad=True)
        self._timestamp: datetime = datetime.now()

    @property
    def actions(self):
        return self._actions

    @property
    def act_requires_grad(self):
        return self.acts_required_grad

    @property
    def observations(self):
        return self._observations

    def _set_actions(self) -> None:
        self._actions = [Action(config=ac) for ac in self._config.actions]
        # self._actions = {ac.key: ac for ac in self._config.actions}
        self._use_unnormed_act = self._config.use_unnormed_act

    def _set_observations(self):
        self._observations = [
            Observation(config=oc) for oc in self._config.observations
        ]
        self._use_unnormed_obs = self._config.use_unnormed_obs

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
            base_env.eplus_cfd.timestamp = self._timestamp
            self._use_simulation_time = True
        else:
            logger.info("Using real-world time")
            self._use_simulation_time = False

    @abstractmethod
    def _reset_data(self) -> None:
        pass

    @abstractmethod
    def format_data(self, **kwargs) -> Batch:
        pass


    @abstractmethod
    def run(self, **kwargs) -> Batch:
        pass
