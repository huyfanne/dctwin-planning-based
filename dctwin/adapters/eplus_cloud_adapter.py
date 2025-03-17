import csv
import numpy as np
from typing import Tuple, Any, Union, List
from pathlib import Path

from cloudtwin.manager import CloudManager

from dctwin.utils import config
from dctwin.third_parties.eplus.core import EplusDockerBackend


class EplusCloudAdapter:
    """
    A class to manage the co-simulation between CloudSim and E+.
    """
    def __init__(
        self,
        eplus_backend: EplusDockerBackend,
        cloud_backend: CloudManager,
    ) -> None:
        self.eplus_manager = eplus_backend
        self.cloud_manager = cloud_backend
        self.episode_idx, self.step_idx = 1, 1

    def _pre_process(self, episode_idx: int = 0) -> None:
        log_dir = Path(config.LOG_DIR).joinpath(
            "cloud_output", f"episode-{episode_idx}"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        config.cloud.file_handler = open(log_dir.joinpath("cloud_log.csv"), "wt", newline='')
        config.cloud.log_handler = csv.DictWriter(
            config.cloud.file_handler,
            fieldnames=(
                ['Current Simulation Time'] +
                ['Computing Demand GT (#CPU)'] +
                ['Computing Demand Pred w. Runtime Update (#CPU)'] +
                ['Computing Demand Pred w/o. Runtime Update (#CPU)'] +
                ["Power Budget (W)"] +
                ["Cluster Power (W)"] +
                ["Num Incoming Jobs"] +
                ["Num Waiting Jobs"] +
                ["Num Running Jobs"] +
                ["Num Finished Jobs"] +
                ["Num Incoming Tasks"] +
                ["Num Started Tasks"] +
                ["Num Waiting Tasks"] +
                ["Num Finished Tasks"] +
                ["Num Running Task Instances"] +
                ["Num Missed Deadline"] +
                ["Avg CPU"] +
                ["Avg Memory"]
                # [f"{server_name}" for server_name in self.cloud_manager.cluster.servers]
            )
        )
        config.cloud.log_handler.writeheader()
        config.cloud.file_handler.flush()

    def _post_processing(self, ):
        log_dict = {}
        log_dict.update({"Current Simulation Time": self.eplus_manager.current_time})
        log_dict.update(
            {
                "Computing Demand GT (#CPU)": self.cloud_manager.cluster.get_computing_demand_true(
                    current_time=int(self.eplus_manager.current_time)
                )
            }
        )
        log_dict.update(
            {
                "Computing Demand Pred w. Runtime Update (#CPU)":
                    self.cloud_manager.cluster.get_computing_demand_pred_with_runtime_update(
                        current_time=int(self.eplus_manager.current_time)
                    )
            }
        )
        log_dict.update(
            {
                "Computing Demand Pred w/o. Runtime Update (#CPU)":
                self.cloud_manager.cluster.get_computing_demand_pred_without_runtime_update(
                    current_time=int(self.eplus_manager.current_time)
                )
            }
        )
        log_dict.update({"Power Budget (W)": self.cloud_manager.cluster.power_budget})
        log_dict.update({"Cluster Power (W)": self.cloud_manager.cluster.total_power})
        log_dict.update({"Num Incoming Jobs": self.cloud_manager.cluster.num_incoming_jobs})
        log_dict.update({"Num Waiting Jobs": len(self.cloud_manager.cluster.waiting_jobs)})
        log_dict.update({"Num Running Jobs": len(self.cloud_manager.cluster.running_jobs)})
        log_dict.update({"Num Running Task Instances": len(self.cloud_manager.cluster.running_task_instances)})
        log_dict.update({"Num Incoming Tasks": self.cloud_manager.cluster.num_incoming_tasks})
        log_dict.update({"Num Started Tasks": self.cloud_manager.cluster.num_started_tasks})
        log_dict.update({"Num Waiting Tasks": self.cloud_manager.cluster.num_pending_tasks})
        log_dict.update({"Num Finished Jobs": self.cloud_manager.cluster.num_finished_jobs})
        log_dict.update({"Num Finished Tasks": self.cloud_manager.cluster.num_finished_tasks})
        log_dict.update({"Num Missed Deadline": self.cloud_manager.cluster.num_missed_deadline})
        log_dict.update({"Avg CPU": np.mean(list(self.cloud_manager.cluster.cpu_utilization.values()))})
        log_dict.update({"Avg Memory": np.mean(list(self.cloud_manager.cluster.mem_utilization.values()))})
        # log_dict.update(self.cloud_manager.cluster.cpu_utilization)
        config.cloud.log_handler.writerow(log_dict)
        config.cloud.file_handler.flush()

    def run(self, episode_idx) -> Tuple[np.ndarray, Any]:
        self._pre_process(episode_idx)
        self.episode_idx = episode_idx
        eplus_obs, done = self.eplus_manager.run(episode_idx)
        self.cloud_manager.accept_workload(
            current_time=int(self.eplus_manager.current_time)
        )
        cloud_pbs = self.cloud_manager.sim(
            current_time=int(self.eplus_manager.current_time)
        )
        obs = np.concatenate([cloud_pbs, eplus_obs])
        return obs, done

    def send_action(
        self,
        capacity_budget: float,
        eplus_actions: np.ndarray | List
    ) -> None:
        self.step_idx += 1
        self.cloud_manager.set_power_budget(
            capacity_budget=capacity_budget
        )
        self.eplus_manager.send_action(eplus_actions)

    def receive_status(self) -> Tuple[Union[List[float], None, np.ndarray], bool]:
        # receive the status from the energy simulator
        eplus_obs, done = self.eplus_manager.receive_status()
        # update the cluster status and log cluster status
        self.cloud_manager.update_states(
            current_time=int(self.eplus_manager.current_time)
        )
        # log the cluster status
        self._post_processing()
        # add new jobs to the cluster
        self.cloud_manager.accept_workload(
            current_time=int(self.eplus_manager.current_time)
        )
        # run cluster simulator to get the equivalent CPU utilization for the next time step
        avg_cpu_util = self.cloud_manager.sim(
            current_time=int(self.eplus_manager.current_time)
        )
        # concatenate the equivalent CPU utilization with the eplus output
        obs = np.concatenate([avg_cpu_util, eplus_obs])
        return obs, done
