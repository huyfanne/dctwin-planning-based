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
import torch


class BaseManager(ABC):
    """ Base class for all data center environments.
    """

    def __init__(
        self,
        config: DTEngineConfig,
        log_results: bool = True,
    ) -> None:
        super().__init__()
        # set up basics
        self._config = config
        self._time_step = 1 / self._config.simulation_time_config.number_of_timesteps_per_hour * 3600  # in seconds
        # Set up actions
        self._set_actions()
        # set up observations
        self._set_observations()
        # set up simulation time
        self._set_simulation_time()
        # reset observation and action data
        self._current_time = 0
        self._episode_idx = 0
        self._fieldnames = ["Timestamp"]
        self._log_results = log_results

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
        if self._log_results:
            self._pre_process()
        self.done = False

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
            end_month = self._config.simulation_time_config.end_month
            end_day_of_month = self._config.simulation_time_config.end_day_of_month
            self._starting_timestamp = datetime(
                year=year, month=begin_month, day=begin_day_of_month
            )
            self._ending_timestamp = datetime(
                year=year, month=end_month, day=end_day_of_month
            )
            self._timestamp_interval = timedelta(
                minutes=int(60 / self._config.simulation_time_config.number_of_timesteps_per_hour)
            )
            self._timestamp = self._starting_timestamp
            self._use_simulation_time = True
        else:
            logger.info("Using real-world time")
            self._use_simulation_time = False

    def _pre_process(self) -> None:
        """
        Create the log file for the simulation results
        """
        logger.info(f"creating log file of episode-{self._episode_idx}")
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
            {"Timestamp": datetime.fromtimestamp(
                self._timestamp.timestamp() + self._current_time
            ).strftime("%Y-%m-%d %H:%M:%S")}
        )
        for obj_name, obj in data.items():
            try:
                for key in obj.keys():
                    try:
                        log_dict.update({f"{obj_name}:{key}": obj[key].item()})
                    except:
                        log_dict.update({f"{obj_name}:{key}": 0.})
            except AttributeError:
                log_dict.update({f"{obj_name}": obj.item()})
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
