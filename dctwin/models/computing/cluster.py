from typing import Union, Dict

import numpy as np
import torch.nn

from forecaster.workload import DurationPredictor
from dclib.workloads.vm import Job
from dclib.ite.servers.server import Server


class Cluster:
    def __init__(
        self,
        servers: Dict[str, Server],
        time_step: int,
        num_steps: int,
        workload_duration_estimator: DurationPredictor = None,
    ):
        # parse building description file to obtain the configuration of each server in the cluster
        self.servers = servers
        self.workload_duration_estimator = workload_duration_estimator

        self.running_jobs: dict = {}
        self.waiting_jobs: dict = {}

        self.num_incoming_jobs: int = 0
        self.num_started_jobs: int = 0
        self.num_finished_jobs: int = 0
        self.num_incoming_tasks: int = 0
        self.num_started_tasks: int = 0
        self.num_finished_tasks: int = 0
        self.num_finished_task_instances: int = 0
        self.num_missed_deadline: int = 0
        self.average_job_waiting_time: int = 0

        self.carbon_emissions: int = 0
        self.total_cluster_power: float = 0.0
        self.power_budget: float = np.Inf

        self.time_step: Union[int, float] = time_step
        self.num_time_step_per_hour: int = 3600 // time_step
        self.computing_demand_gt: np.ndarray = np.zeros(
            num_steps + 1
        )  # +1 for last time step, avoiding out of bound
        self.computing_demand_pred_with_run_time_update: np.ndarray = np.zeros(
            num_steps + 1
        )
        self.computing_demand_pred_without_run_time_update: np.ndarray = np.zeros(
            num_steps + 1
        )

    def start_instance(self, server_id: str, job_id: str, task_id: str, clock: float):
        """
        Start a task instance on a server.
        """
        next_ptr = (
            self.running_jobs[job_id].running_tasks[task_id].next_instance_pointer
        )
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].allocated_server_name = server_id
        self.servers[server_id].computing.run_task_instance(
            self.running_jobs[job_id].running_tasks[task_id].task_instances[next_ptr]
        )
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].started = True
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].finished = False
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].released = False
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].start_time = clock
        self.running_jobs[job_id].running_tasks[task_id].task_instances[
            next_ptr
        ].finish_time = (
            self.running_jobs[job_id]
            .running_tasks[task_id]
            .task_instances[next_ptr]
            .duration
            + clock
        )
        # update cluster power after start a task instance
        cpu_util = (
            self.running_jobs[job_id]
            .running_tasks[task_id]
            .task_instances[next_ptr]
            .cpu
            / self.servers[server_id].computing.cpu_capacity
        )
        mem_util = (
            self.running_jobs[job_id]
            .running_tasks[task_id]
            .task_instances[next_ptr]
            .memory
            / self.servers[server_id].computing.mem_capacity
        )
        disk_util = (
            self.running_jobs[job_id]
            .running_tasks[task_id]
            .task_instances[next_ptr]
            .disk
            / self.servers[server_id].computing.disk_capacity
        )
        self.total_cluster_power += self.servers[server_id].power.calc(
            cpu=cpu_util, mem=mem_util, disk=disk_util
        )
        # move the ptr to the next task instance
        self.running_jobs[job_id].running_tasks[task_id].next_instance_pointer += 1

        # update the number of started tasks
        self.num_started_tasks += 1

    def add_jobs(self, current_time: int, jobs: dict[str, Job]):
        """
        Add a list of jobs to the cluster.
        """
        self.num_incoming_jobs = len(jobs)
        self.num_incoming_tasks = 0
        for job_name, job in jobs.items():
            self.num_incoming_tasks += len(job.waiting_tasks)
        # get the lifetime estimation for each task in the current batch of jobs
        time_idx = current_time // self.time_step
        for job_name, job in jobs.items():
            prev_dur_str = "|"
            num_tasks = len(job.waiting_tasks)
            job.submission_time = current_time
            for task_name, waiting_task in job.waiting_tasks.items():
                waiting_task.submission_time = current_time
                flav_str = waiting_task.flav_type
                # predict the duration of the task
                if self.workload_duration_estimator is None:
                    task_dur_str, task_dur, task_dur_dist = None, None, None
                else:
                    task_dur_str, task_dur, task_dur_dist = (
                        self.workload_duration_estimator.predict(
                            timestamp=current_time + 1943400,
                            current_flav_str=flav_str,
                            prev_dur_str=prev_dur_str,
                            num_tasks_in_batch=num_tasks,
                        )
                    )
                # get the task lifetime estimation
                waiting_task.duration_estimation = task_dur
                waiting_task.duration_distribution = task_dur_dist
                waiting_task.slack_time = np.clip(
                    waiting_task.deadline - waiting_task.duration, 0, np.inf
                )  # slack time is the time left for the task to finish after the task is submitted
                prev_dur_str = task_dur_str
                # update the true computing demand with the perfect incoming task information
                end_idx_true = int(waiting_task.duration // self.time_step + time_idx)
                self.computing_demand_gt[time_idx:end_idx_true] += waiting_task.cpu
                # only calculate the estimated computing demand when the duration estimator is available
                if self.workload_duration_estimator is not None:
                    end_idx_pred = int(
                        waiting_task.duration_estimation // self.time_step + time_idx
                    )
                    self.computing_demand_pred_without_run_time_update[
                        time_idx:end_idx_pred
                    ] += waiting_task.cpu
                    self.computing_demand_pred_with_run_time_update[
                        time_idx:end_idx_pred
                    ] += waiting_task.cpu

            # add the job to the waiting queue
            self.waiting_jobs.update({job_name: job})

    def update_job_status(self, clock: float):
        """
        Update the status of all running jobs in this cluster given the current simulation time. At a specific timestamp,
        an instance of a task may finish its execution. In this case, the task instance will be removed from the machine.
        Otherwise, the remaining time of the task instance will be updated.
        :param clock:
        :return:
        """
        # Update status of running task instances
        for job_name, job in self.running_jobs.items():
            for task_name, task in job.running_tasks.items():
                for task_instance in task.task_instances:
                    # update the task instance status
                    finished_condition1 = (
                        task_instance.started and task_instance.finish_time < clock
                    )
                    finished_condition2 = (
                        task_instance.started
                        and task_instance.finish_time - task.submission_time
                        > task.deadline
                    )
                    if finished_condition1 or finished_condition2:
                        if not task_instance.released:
                            task_instance.running_time_at_one_slot = (
                                task_instance.remaining_time
                            )
                            task_instance.running_time += (
                                task_instance.running_time_at_one_slot
                            )
                            task_instance.remaining_time = 0
                            # see if the task instance is finished before the deadline
                            if (
                                task_instance.finish_time - task.submission_time
                                > task.deadline
                            ):
                                self.num_missed_deadline += 1
                            task_instance.finished = True
                            # update cluster power after finish a task instance
                            task_cpu_util = (
                                task_instance.cpu
                                / self.servers[
                                    task_instance.allocated_server_name
                                ].computing.cpu_capacity
                            )
                            task_mem_util = (
                                task_instance.memory
                                / self.servers[
                                    task_instance.allocated_server_name
                                ].computing.mem_capacity
                            )
                            task_disk_util = (
                                task_instance.disk
                                / self.servers[
                                    task_instance.allocated_server_name
                                ].computing.disk_capacity
                            )
                            self.total_cluster_power -= self.servers[
                                task_instance.allocated_server_name
                            ].power.calc(task_cpu_util, task_mem_util, task_disk_util)
                            # update the number of finished task instances
                            self.num_finished_task_instances += 1
                    else:
                        # if the running task is still running
                        task_instance.remaining_time -= self.time_step
                        task_instance.running_time += self.time_step
                        task_instance.running_time_at_one_slot = self.time_step
                        # update the task duration estimation if the duration distribution is available
                        if self.workload_duration_estimator is not None:
                            current_idx = int(clock // self.time_step)
                            start_idx = int(task_instance.start_time // self.time_step)
                            if task_instance.running_time > task.duration_estimation:
                                for (
                                    dur_bin_idx,
                                    dur_boundary,
                                ) in self.workload_duration_estimator.dur_map.items():
                                    if (
                                        dur_boundary["min"]
                                        <= task_instance.running_time
                                        <= dur_boundary["max"]
                                    ):
                                        break
                                dur_bin_idx = int(dur_bin_idx)
                                prob_elapsed_time = torch.sum(
                                    task.duration_distribution[:dur_bin_idx]
                                )
                                # update the duration distribution using observed elapsed time
                                task.duration_distribution[:dur_bin_idx] = 0
                                task.duration_distribution[dur_bin_idx:] /= (
                                    1 - prob_elapsed_time
                                )
                                # update duration estimation
                                adjusted_dur_bin = (
                                    torch.distributions.Categorical(
                                        probs=task.duration_distribution
                                    )
                                    .sample()
                                    .item()
                                )
                                # adjusted_dur_bin = adjusted_dur_bin if adjusted_dur_bin < 23 else 22
                                task.duration_estimation = self.workload_duration_estimator.convert_time_index_to_duration(
                                    adjusted_dur_bin
                                )
                                adjusted_end_idx = int(
                                    task.duration_estimation // self.time_step
                                    + start_idx
                                )
                                # update the computing demand estimation
                                self.computing_demand_pred_with_run_time_update[
                                    current_idx:adjusted_end_idx
                                ] += task.cpu

        # Stop the finished task instances, running jobs and running tasks
        finished_job_id = []
        for job_name, job in self.running_jobs.items():
            finished_task_id = []
            for task_name, task in job.running_tasks.items():
                for task_instance in task.task_instances:
                    finished_condition1 = (
                        task_instance.started and task_instance.finish_time < clock
                    )
                    finished_condition2 = (
                        task_instance.started
                        and task_instance.finish_time - task.submission_time
                        > task.deadline
                    )
                    if finished_condition1 or finished_condition2:
                        if not task_instance.released:
                            self.servers[
                                task_instance.allocated_server_name
                            ].computing.stop_task_instance(task_instance)
                            task_instance.released = True
                            if (
                                task_instance.task_instance_index
                                == len(task.task_instances) - 1
                            ):
                                task.finished = True
                                finished_task_id.append(task_name)
                                # update the number of finished tasks
                                self.num_finished_tasks += 1
                        # update the computing demand estimation
                        task_start_idx = int(task.submission_time // self.time_step)
                        end_idx_pred = int(
                            task.duration_estimation // self.time_step + task_start_idx
                        )
                        current_idx = int(clock // self.time_step)
                        self.computing_demand_pred_with_run_time_update[
                            current_idx:end_idx_pred
                        ] -= task.cpu

            for task_id in finished_task_id:
                job.running_tasks.pop(task_id)

            if len(job.running_tasks) == 0 and len(job.waiting_tasks) == 0:
                job.finished = True
                finished_job_id.append(job_name)
                # update the number of finished jobs
                self.num_finished_jobs += 1
        # Remove the finished jobs
        for job_id in finished_job_id:
            self.running_jobs.pop(job_id)

        # Update slack time of all waiting tasks (waiting tasks in "waiting jobs" + waiting tasks in "running jobs")
        removed_job = []
        for job_name, job in self.waiting_jobs.items():
            removed_tasks = []
            for task_name, task in job.waiting_tasks.items():
                task.slack_time = np.clip(task.slack_time - self.time_step, 0, np.inf)
                if task.slack_time == 0:
                    self.num_missed_deadline += 1
                    removed_tasks.append(task_name)
            for task_name in removed_tasks:
                job.waiting_tasks.pop(task_name)
            if len(job.waiting_tasks) == 0:
                removed_job.append(job_name)
        # remove the job that all its tasks miss the deadline
        for job_name in removed_job:
            self.waiting_jobs.pop(job_name)

        # remove the tasks in a running job that miss the deadline
        for job_name, job in self.running_jobs.items():
            removed_tasks = []
            for task_name, task in job.waiting_tasks.items():
                task.slack_time = np.clip(task.slack_time - self.time_step, 0, np.inf)
                if task.slack_time == 0:
                    self.num_missed_deadline += 1
                    removed_tasks.append(task_name)
            for task_name in removed_tasks:
                job.waiting_tasks.pop(task_name)

    def get_computing_demand_true(self, current_time: int):
        return self.computing_demand_gt[current_time // self.time_step - 1]

    def get_computing_demand_pred_with_runtime_update(self, current_time: int):
        return self.computing_demand_pred_with_run_time_update[
            current_time // self.time_step - 1
        ]

    def get_computing_demand_pred_without_runtime_update(self, current_time: int):
        return self.computing_demand_pred_without_run_time_update[
            current_time // self.time_step - 1
        ]

    def reset(self):
        self.running_jobs = {}
        self.waiting_jobs = {}
        self.num_finished_jobs = 0
        self.num_finished_tasks = 0
        self.num_finished_task_instances = 0
        self.total_cluster_power = 0
        self.power_budget = np.Inf
        for server_name, server in self.servers.items():
            server.computing.remaining_cpu = server.computing.cpu_capacity
            server.computing.remaining_mem = server.computing.mem_capacity
            server.computing.remaining_disk = server.computing.disk_capacity
            server.computing.task_instances = {}

    def update_average_job_waiting_time(self, job_id, current_time):
        if job_id in self.running_jobs.keys():
            job = self.running_jobs[job_id]
            num_started_jobs = self.num_started_jobs + 1
            average_job_waiting_time = (
                self.average_job_waiting_time * self.num_started_jobs
                + (current_time - job.submission_time)
            ) / num_started_jobs
            self.average_job_waiting_time = average_job_waiting_time
            self.num_started_jobs = num_started_jobs

    @property
    def rated_power(self):
        res = 0.0
        for server_name, server in self.servers.items():
            res += (
                server.power.rated_cpu_power
                + server.power.rated_mem_power
                + server.power.rated_disk_power
            )
        return res

    @property
    def total_power(self):
        return sum(list(self.server_power.values()))

    @property
    def cpu_capacity(self):
        cpu_capacity = {
            server_name: server.computing.cpu_capacity
            for server_name, server in self.servers.items()
        }
        return sum(list(cpu_capacity.values()))

    @property
    def mem_capacity(self):
        mem_capacity = {
            server_name: server.computing.cpu_capacity
            for server_name, server in self.servers.items()
        }
        return sum(list(mem_capacity.values()))

    @property
    def disk_capacity(self):
        disk_capacity = {
            server_name: server.computing.disk_capacity
            for server_name, server in self.servers.items()
        }
        return sum(list(disk_capacity.values()))

    @property
    def remaining_cpu(self):
        return {
            server_name: server.computing.remaining_cpu
            for server_name, server in self.servers.items()
        }

    @property
    def remaining_mem(self):
        return {
            server_name: server.computing.remaining_mem
            for server_name, server in self.servers.items()
        }

    @property
    def remaining_disk(self):
        return {
            server_name: server.computing.remaining_disk
            for server_name, server in self.servers.items()
        }

    @property
    def num_pending_tasks(self):
        res = 0
        for job_name, job in self.waiting_jobs.items():
            for task_name, task in job.waiting_tasks.items():
                res += task.num_instances
        for job_name, job in self.running_jobs.items():
            for task_name, task in job.waiting_tasks.items():
                res += task.num_instances
        return res

    @property
    def running_task_instances(self):
        """
        Get all running task instances in this cluster.
        :return:
        """
        task_instances = []
        for job_name, job in self.running_jobs.items():
            for task_name, task in job.running_tasks.items():
                for instance in task.task_instances:
                    if instance.started and not instance.finished:
                        task_instances.append(task_instances)
        return task_instances

    @property
    def cpu_utilization(self):
        return {
            server_name: 1
            - server.computing.remaining_cpu / server.computing.cpu_capacity
            for server_name, server in self.servers.items()
        }

    @property
    def mem_utilization(self):
        return {
            server_name: 1
            - server.computing.remaining_mem / server.computing.mem_capacity
            for server_name, server in self.servers.items()
        }

    @property
    def disk_utilization(self):
        return {
            server_name: 1
            - server.computing.remaining_disk / server.computing.disk_capacity
            for server_name, server in self.servers.items()
        }

    @property
    def server_power(self):
        server_power = {
            server_name: 0.0 for server_name, server in self.servers.items()
        }
        for job_name, job in self.running_jobs.items():
            for task_name, task in job.running_tasks.items():
                for instance in task.task_instances:
                    if instance.started and not instance.finished:
                        instance_cpu_util = (
                            instance.cpu
                            / self.servers[
                                instance.allocated_server_name
                            ].computing.cpu_capacity
                        )
                        instance_mem_util = (
                            instance.memory
                            / self.servers[
                                instance.allocated_server_name
                            ].computing.mem_capacity
                        )
                        instance_disk_util = (
                            instance.disk
                            / self.servers[
                                instance.allocated_server_name
                            ].computing.disk_capacity
                        )
                        instance_power = self.servers[
                            instance.allocated_server_name
                        ].power.calc(
                            cpu=instance_cpu_util,
                            mem=instance_mem_util,
                            disk=instance_disk_util,
                        )
                        instance_energy = (
                            instance_power * instance.running_time_at_one_slot
                        )
                        server_power[instance.allocated_server_name] += instance_energy
        for server_name, power in server_power.items():
            server_power[server_name] = power / self.time_step
        return server_power
