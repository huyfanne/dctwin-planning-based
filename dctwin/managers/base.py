import csv
from abc import abstractmethod, ABC
from datetime import datetime, timedelta
from typing import Dict
from pathlib import Path

from loguru import logger

from dctwin.utils import (
    DTEngineConfig,
    config as base_env,
)

from dctwin.data import (
    Action,
    Observation
)

from dctwin.data.batch import Batch
from dclib import Building, Room
import torch


class BaseManager(ABC):
    """ Base class for all data center environments.
    """

    def __init__(
        self,
        config: DTEngineConfig,
        model: Building | Room,
        device_key_mapping: Dict = None,
        ds=None,
    ) -> None:
        super().__init__()
        # set up basics
        self._config = config
        self._model = model
        self._device_key_mapping = device_key_mapping
        self._time_step = 1 / self._config.simulation_time_config.number_of_timesteps_per_hour * 3600  # in seconds
        # Set up actions
        self._set_actions()
        # set up observations
        self._set_observations()
        # set up simulation time
        self._set_simulation_time()
        # reset observation and action data
        self._ds = ds
        self._current_time = 0
        self._episode_idx = 0
        self._fieldnames = ["Timestamp"]

    def _reset_acts_require_grad(self):
        self._acts_require_grad = torch.tensor([], requires_grad=True)

    @abstractmethod
    def _reset_data(self) -> None:
        pass

    def reset(self) -> None:
        self._current_time = 0
        self._episode_idx += 1
        self._reset_data()
        # set up the result logging
        if self._episode_idx == 1:
            self._pre_process()

    def _set_actions(self) -> None:
        self._actions = [Action(config=ac) for ac in self._config.actions]

    def _set_observations(self):
        self._observations = [Observation(config=oc) for oc in self._config.observations]

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
                minutes=int(60 / self._config.simulation_time_config.number_of_timesteps_per_hour)
            )
            self._timestamp = self._starting_timestamp
            base_env.timestamp = self._timestamp
            self._use_simulation_time = True
        else:
            logger.info("Using real-world time")
            self._use_simulation_time = False

    def _pre_process(self) -> None:
        """
        Create the log file for the simulation results
        """
        base_env.case_dir = Path(base_env.LOG_DIR).joinpath(
            f"dctwin_output/episode-{self._episode_idx}"
        )
        Path(base_env.case_dir).mkdir(parents=True, exist_ok=True)
        filename = Path(base_env.case_dir).joinpath("dctwin_output.csv")
        base_env.file_handler = open(filename, "wt", newline="")
        base_env.log_handler = csv.DictWriter(
            base_env.file_handler,
            fieldnames=self._fieldnames,
        )
        base_env.log_handler.writeheader()
        base_env.file_handler.flush()

    def _post_process(self, data: Dict) -> None:
        """
        Log the simulation results
        """
        log_dict = {}
        log_dict.update(
            {"Timestamp": self._current_time}
        )
        for obj_name, obj in data.items():
            for key in obj.keys():
                try:
                    log_dict.update({f"{obj_name}:{key}": obj[key].item()})
                except:
                    log_dict.update({f"{obj_name}:{key}": 0.})
        base_env.log_handler.writerow(log_dict)
        base_env.file_handler.flush()

    @property
    def actions(self):
        return self._actions

    @property
    def acts_require_grad(self):
        return self._acts_require_grad

    @property
    def observations(self):
        return self._observations

    @abstractmethod
    def format_actions(self, **kwargs) -> Batch:
        pass

    @abstractmethod
    def run(self, **kwargs):
        pass
