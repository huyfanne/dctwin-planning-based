import shutil
import csv
import json
import docker
import numpy as np
from typing import Dict, Tuple, Any, Union, List
from pathlib import Path
from sympy import symbols, solve
import torch

from dctwin.utils import config

from dctwin.interfaces.managers import CFDManager
from dctwin.backends import EplusBackend
from dctwin.models import Room


class EplusCFDAdapter:
    """
    A class to manage the co-simulation between CFD and E+.

    :param room: the room object model for data hall
    :param eplus_backend: the E+ backend to be used
    :param mesh_process: the number of processes to be used for meshing
    :param solve_process: the number of processes to be used for solving
    :param steady: whether to run steady state simulation
    :param write_interval: the interval to write the results
    :param end_time: the end time of the simulation
    :param field_config: the configuration of the field variables
    :param pod_method: the method to be used for POD
    :param docker_client: the docker client to be used for running the docker container

    """

    rho_air = 1.19  # air density kg/m^3

    def __init__(
        self,
        room: Room,
        eplus_backend: EplusBackend,
        mesh_process: int = 8,
        solve_process: int = 8,
        steady: bool = True,
        write_interval: int = None,
        end_time: int = None,
        field_config: Dict = None,
        pod_method: str = "GP",
        docker_client: docker.DockerClient = None,
    ) -> None:

        self.cfd_manager = CFDManager(
            room=room,
            mesh_process=mesh_process,
            solve_process=solve_process,
            steady=steady,
            write_interval=write_interval,
            end_time=end_time,
            field_config=field_config,
            pod_method=pod_method,
            docker_client=docker_client,
        )

        self.eplus_manager = eplus_backend
        self.cfd_sensor_obs = None
        self.episode_idx, self.step_idx = 1, 1
        self.server_inlet_temps = {}

        with open(config.co_sim.idf2room_map, "r") as f:
            self.idf2room_mapper = json.load(f)

    def _pre_process(self, episode_idx: int = 0) -> None:
        """ create case directory and backup model files"""
        config.cfd.case_dir = Path(config.LOG_DIR).joinpath(
            "cfd_output", f"episode-{episode_idx}"
        )
        Path(config.cfd.case_dir).mkdir(exist_ok=True, parents=True)
        room_path = Path(config.cfd.case_dir).joinpath(config.cfd.geometry_file.name)
        idf2room_path = Path(config.cfd.case_dir).joinpath(config.co_sim.idf2room_map.name)
        shutil.copy(config.cfd.geometry_file, room_path)
        shutil.copy(config.co_sim.idf2room_map, idf2room_path)
        # init log file for cfd results
        filename = Path(config.cfd.case_dir).joinpath('cfd_log.csv')
        config.cfd.file_handler = open(filename, "wt")
        config.cfd.log_handler = csv.DictWriter(
            config.cfd.file_handler,
            fieldnames=(
                    ['timestamp'] +
                    [f"{crac_id} (C)" for crac_id in self.cfd_manager.parser.model.objects.acus] +
                    [f"{crac_id} (m3/s)" for crac_id in self.cfd_manager.parser.model.objects.acus] +
                    ["Total IT Power (w)"] +
                    ["Total IT Volume Flow Rate (m3/s)"] +
                    [f"{sensor_id} (C)" for sensor_id in self.cfd_manager.parser.model.objects.sensors]
            )
        )
        config.cfd.log_handler.writeheader()
        config.cfd.file_handler.flush()

    def _post_processing(
        self,
        temperature: Union[torch.Tensor, np.ndarray],
        server_powers: Dict,
        server_volume_flow_rates: Dict,
        crac_setpoints: Dict,
        crac_volume_flow_rates: Dict,
        log_to_csv: bool = True
    ) -> Tuple[list[Any], list[Any], float]:
        """Post-processing to collect sensor observation, server inlet temperature
        and CRAC return temperature
        """
        # transform temperature to numpy array
        if type(temperature) == torch.Tensor:
            temperature = temperature.detach().cpu().numpy().ravel()
        # get return temperature for each air loop
        return_temps = {}
        for it_equipment in self.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled:
            _crac = self.cfd_manager.object_mesh_index["cracs"]
            _air_loop_id = self.idf2room_mapper[it_equipment.name]["crac"]
            return_temp = temperature[_crac[_air_loop_id]["return"]]
            return_temps[_air_loop_id] = return_temp
        return_temps = [val for val in return_temps.values()]

        # get boundary conditions and sensor observation
        cfd_sensor_obs_list, cfd_log_dict = [], {}
        total_server_powers, total_server_flow_rates = 0, 0
        cfd_log_dict.update({"timestamp": config.co_sim.timestamp})

        for crac_id, _ in self.cfd_manager.object_mesh_index["cracs"].items():
            cfd_log_dict.update({f"{crac_id} (C)": round(crac_setpoints[crac_id], 3)})
            cfd_log_dict.update({f"{crac_id} (m3/s)": round(crac_volume_flow_rates[crac_id], 3)})

        for server_id, _ in self.cfd_manager.object_mesh_index["servers"].items():
            total_server_powers += server_powers[server_id]
            total_server_flow_rates += server_volume_flow_rates[server_id]

        # get server inlet temperature
        for server_id, server_temp in self.cfd_manager.object_mesh_index["servers"].items():
            inlet_temp = temperature[int(server_temp["inlet"])]
            self.server_inlet_temps[server_id] = inlet_temp

        cfd_log_dict.update(
            {"Total IT Power (w)": round(total_server_powers, 3)}
        )
        cfd_log_dict.update(
            {"Total IT Volume Flow Rate (m3/s)": round(total_server_flow_rates, 3)}
        )

        for sensor_id, index in self.cfd_manager.object_mesh_index["sensors"].items():
            cfd_sensor_obs_list.append(temperature[index])
            cfd_log_dict.update({f"{sensor_id} (C)": round(temperature[index], 3)})

        if log_to_csv:
            config.cfd.log_handler.writerow(cfd_log_dict)
            config.cfd.file_handler.flush()

        return cfd_sensor_obs_list, return_temps, total_server_powers

    def _scale_server_flow_rate(
        self,
        boundary_conditions: Dict,
        crac2server_flow_ratio: float = 0.8
    ) -> Dict:
        """
        scale total server flow rate as a ratio of total supply air flow rate
        """
        for it_equipment in self.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled:
            uid = self.idf2room_mapper[it_equipment.name]["crac"]
            supply_flow_rate = boundary_conditions["crac_volume_flow_rates"][uid]
            sum_server_flow_rate = 0
            for server_id in self.idf2room_mapper[it_equipment.name]["servers"]:
                sum_server_flow_rate += boundary_conditions["server_volume_flow_rates"][server_id]
            scale_factor = supply_flow_rate * crac2server_flow_ratio / sum_server_flow_rate
            for server_id in self.idf2room_mapper[it_equipment.name]["servers"]:
                boundary_conditions["server_volume_flow_rates"][server_id] *= scale_factor
        return boundary_conditions

    def run(self, episode_idx) -> Tuple[np.ndarray, Any]:
        self.episode_idx = episode_idx
        eplus_obs, done = self.eplus_manager.run(episode_idx)
        init_boundary_condition = self.cfd_manager.parser.format_boundary_conditions
        init_boundary_condition = self._scale_server_flow_rate(
            boundary_conditions=init_boundary_condition
        )
        self._pre_process(episode_idx=episode_idx)
        cfd_obs = self.cfd_manager.run(
            case_idx=self.step_idx,
            episode_idx=episode_idx,
            dry_run=config.cfd.dry_run,
            **init_boundary_condition
        )
        self.cfd_sensor_obs, return_temp, _ = self._post_processing(
            temperature=cfd_obs,
            **init_boundary_condition
        )
        return np.concatenate([eplus_obs, self.cfd_sensor_obs], axis=0), done

    def _compute_equivalent_inlet_temperature(
        self,
        parsed_actions: Dict,
        total_server_power: float
    ) -> List[float]:
        server_inlet_temps = []
        for it_equipment in self.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled:
            equation = self.eplus_manager.idf_parser.compute_server_power(
                utilization=parsed_actions["cpu_loading_schedule"],
                inlet_temperature=symbols("inlet_temperature", positive=True),
                name=it_equipment.name,
            ) * len(self.idf2room_mapper[it_equipment.name]["servers"]) - total_server_power
            inlet_temp_list = solve(equation)
            uid = self.idf2room_mapper[it_equipment.name]["crac"]
            server_inlet_temp = parsed_actions[f"{uid}_setpoint"]
            for value in inlet_temp_list:
                if value > parsed_actions[f"{uid}_setpoint"]:
                    server_inlet_temp = value
            server_inlet_temps.append(server_inlet_temp)
        return server_inlet_temps

    def map_boundary_conditions(self, parsed_actions: Dict) -> Dict:
        """
        Map the action dict into boundary condition dict with a given format.
        Boundary conditions should include supply temperature, supply
        volumetric flow rate, server powers and server flow rates.
        Server power and server flow rate are computed in a model-based manner
        with the model from Eplus. The curve parameters for the server power model
        and flow rate model are from parsing the idf file automatically.
        """
        boundary_conditions = {
            "crac_setpoints": {}, "crac_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
        }
        # set crac supply temperature and supply volumetric flow rate
        for crac in self.eplus_manager.idf_parser.epm.AirLoopHVAC:
            uid = self.idf2room_mapper[crac.name]
            boundary_conditions["crac_setpoints"][uid] = parsed_actions[f"{uid}_setpoint"]
            boundary_conditions["crac_volume_flow_rates"][uid] = parsed_actions[f"{uid}_flow_rate"] / self.rho_air

        # compute server power and volumetric flow rate
        for it_equipment in self.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled:
            assert len(self.idf2room_mapper[it_equipment.name]["servers"]) == self.eplus_manager.idf_parser.number_of_units[it_equipment.name], \
                "The number of servers in the room should be equal to the number of units in the idf file."
            for server_id in self.idf2room_mapper[it_equipment.name]["servers"]:
                # The calculation assumes that the servers are homogeneous and use the same curve
                # parameters for power and flow rate models.
                # TODO: can be extended to heterogeneous servers with different curve parameters
                heat_load = self.eplus_manager.idf_parser.compute_server_power(
                    utilization=parsed_actions["cpu_loading_schedule"],
                    inlet_temperature=self.server_inlet_temps[server_id],
                    name=it_equipment.name
                )
                volume_flow_rate = self.eplus_manager.idf_parser.compute_server_flow_rate(
                    utilization=parsed_actions["cpu_loading_schedule"],
                    inlet_temperature=self.server_inlet_temps[server_id],
                    name=it_equipment.name
                )
                boundary_conditions["server_powers"][server_id] = heat_load
                boundary_conditions["server_volume_flow_rates"][server_id] = volume_flow_rate

        # scale server flow rate so that the summation of server flow rate will not exceed supply flow rate
        boundary_conditions = self._scale_server_flow_rate(boundary_conditions=boundary_conditions)
        return boundary_conditions

    def send_action(self, parsed_actions) -> None:
        """
        Run simulation with hybrid environment. The data hall simulation is
        conducted by either CFD simulation or POD simulation. If the POD files
        are provided, POD simulation is conducted to achieve acceleration. The return
        temperature is obtained from CFD/POD simulation and feeds bach to Eplus to
        compute the corresponding power consumption.
        """
        self.step_idx += 1
        boundary_conditions = self.map_boundary_conditions(parsed_actions)
        # run CFD/POD simulation
        temperature = self.cfd_manager.run(
            case_idx=self.step_idx,
            episode_idx=self.episode_idx,
            dry_run=config.cfd.dry_run,
            **boundary_conditions
        )
        # post-processing CFD/POD simulation result to obtain return temperature
        self.cfd_sensor_obs, return_temp, total_server_power = self._post_processing(
            temperature=temperature,
            **boundary_conditions
        )
        server_inlet_temperatures = self._compute_equivalent_inlet_temperature(
            parsed_actions=parsed_actions,
            total_server_power=total_server_power,
        )
        # add two approach temperatures (a.k.a. return temperature actually) to the end of the raw action array
        send_actions = []
        for value in parsed_actions.values():
            send_actions.append(value)
        if server_inlet_temperatures is not None:
            send_actions += server_inlet_temperatures
        else:
            send_actions += [0.0]
        send_actions += return_temp
        # send raw action array to Eplus to proceed the energy simulation
        self.eplus_manager.send_action(send_actions)

    def receive_status(self) -> Tuple[Union[List[float], None], bool]:
        # get energy status from Eplus as observation
        eplus_obs, done = self.eplus_manager.receive_status()
        # combine co-sim sensor observation with Eplus observation
        obs = eplus_obs + self.cfd_sensor_obs
        return obs, done
