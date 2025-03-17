import numpy as np
from typing import Union

from forecaster.workload import DurationPredictor

from .job_generator import ClusterTraceJobGenerator

from .scheduler import (
    FistFitScheduler,
    RoundRobinScheduler,
    ShortSlackTimeFirstScheduler,
    SJFScheduler,
    TetrisScheduler
)
from dctwin.models.computing.cluster import Cluster
from .config import CloudConfig

from dclib import Building


class CloudManager:
    """
    Class to manager the simulation of building resource provisioning and job scheduling.
    """
    schedulers = {
        "first_fit": FistFitScheduler,
        "round_robin": RoundRobinScheduler,
        "edf": ShortSlackTimeFirstScheduler,
        "sjf": SJFScheduler,
        "best_fit": TetrisScheduler
    }

    def __init__(
        self,
        cloud_configs: CloudConfig,
        building: Building
    ):
        self.num_ites = building.constructions.num_ites
        # Initialize the building workload generator
        self.job_generator = ClusterTraceJobGenerator(
            trace_file_path=cloud_configs.trace_file
        )
        # Initialize the cluster
        servers = {}
        for zone in building.constructions.zones.values():
            for server_name, server in zone.constructions.servers.items():
                servers[server_name] = server
        workload_duration_estimator = DurationPredictor(
            config=cloud_configs.job_duration_estimator_config
        )
        self.cluster = Cluster(
            servers=servers,
            time_step=cloud_configs.time_step,
            num_steps=cloud_configs.total_time_steps,
            workload_duration_estimator=workload_duration_estimator,
        )
        # Initialize workload scheduler
        self.workload_scheduler = self.schedulers[cloud_configs.schedule_policy]().attach(self.cluster)

    def accept_workload(self, current_time: Union[int, float]) -> None:
        jobs = next(self.job_generator)
        self.cluster.add_jobs(
            current_time=current_time,
            jobs=jobs
        )

    def update_states(self, current_time: Union[int, float]) -> None:
        self.cluster.update_job_status(current_time)

    def set_power_budget(self, capacity_budget: float) -> None:
        self.workload_scheduler.set_power_budget(power_budget=capacity_budget*self.cluster.rated_power)

    def sim(
        self,
        current_time: Union[int, float]
    ) -> Union[float, np.ndarray]:
        self.workload_scheduler.make_decision(current_time=current_time)
        # normalize the CPU load to [-1, 1] for the RL agent
        avg_cpu_load = np.mean(list(self.cluster.cpu_utilization.values()))
        return [avg_cpu_load]*self.num_ites
