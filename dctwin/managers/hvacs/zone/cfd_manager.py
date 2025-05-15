import copy
import os
import shutil
import subprocess
import sys
import platform
import time
import math

import psutil
from typing import Optional, Union, Dict
from collections import OrderedDict
import numpy as np
import docker
import torch
from loguru import logger

from dctwin.third_parties import (
    SteadySolverK8sBackend,
    SteadySolverDockerBackend,
    TransientSolverK8sBackend,
    TransientSolverDockerBackend,
    SnappyHexBackend,
    SnappyHexK8sBackend,
)
from dctwin.third_parties.foam.utils import init_foam
from dctwin.models.cooling.thermodyns.field import PODK8SBackend, PODDockerBackend
from dclib.models.geometry import Vertex

from .utils import (
    check_base_dir,
    read_object_mesh_index,
    read_mesh_coordinates,
    calc_object_mesh_index,
    save_json_file,
    read_temperature,
    read_p,
    read_p_rgh,
    read_u,
    read_sensor_results,
)

from dctwin.utils import config
from dctwin.utils.errors import (
    MeshBuildError,
    FoamSolveError,
)
from dctwin.third_parties.foam.mesh import RackModel, RowRackModel
from dclib.room import Room, Rack, Server
from dclib.data import ServerInputs


class CFDManager:
    """
    A manager for the whole CFD simulation for data hall thermal analysis
    the workflow includes:
    1. build geometry
    2. mesh geometry
    3. solve steady or transient simulation
    4. post process results

    :param room: a room object that contains all rooms
    :param solve_process: number of CPU cores for solving
    :param mesh_process: number of CPU cores for meshing
    :param steady: use steady or transient simulation
    :param write_interval: data write interval for simulation, can be set as 5, 10, 100, etc.
    :param end_time: end step for steady simulation, can be set as 50, 100, 150, etc. Normally 100-500 is enough.
    :param pod_method: POD method, can be GP, Flux, or GP-Flux
    :param docker_client: docker client
    :param is_k8s: whether to use k8s for simulation
    :param k8s_config: k8s configuration
    :param scale_server_flow_rate: whether to scale server flow rate
    :param acu2server_flow_ratio: ratio of acu supply air flow rate to total server flow rate
    :param is_gpu: whether to use GPU for simulation
    """

    def __init__(
        self,
        room: Room,
        solve_process: int = 8,
        mesh_process: int = 8,
        steady: bool = True,
        run_cfd: bool = True,
        write_interval: int = 50,
        end_time: int = 1000,
        pod_method: str = "GP",
        docker_client: docker.DockerClient = None,
        is_k8s: bool = False,
        k8s_config: Dict = None,
        scale_server_flow_rate: bool = False,
        acu2server_flow_ratio: float = 0.9,
        is_gpu: bool = False,
        refinement_level: int = 2,
        is_modulus: bool = False,
        location_in_mesh: Vertex = Vertex(x=0.,y=0.,z=0.),
        openfoam_image = None
    ) -> None:
        self.is_modulus = is_modulus
        if k8s_config is None:
            k8s_config = {}
        if not is_k8s:
            self.docker_client = docker_client if docker_client else docker.from_env()
        self.mesh_backend: Optional[Union[SnappyHexBackend, SnappyHexK8sBackend]] = None
        self.solver_backend: Union[
            None,
            SteadySolverK8sBackend,
            SteadySolverDockerBackend,
            TransientSolverK8sBackend,
            TransientSolverDockerBackend,
        ] = None
        self.pod_backend: Optional[Union[PODDockerBackend, PODK8SBackend]] = None

        self.room: Room = room
        self.steady = steady
        self.run_cfd = run_cfd
        self.solve_process = solve_process
        self.mesh_process = mesh_process
        self.write_interval = write_interval
        self.end_time = end_time
        self.pod_method = pod_method
        self.isk8s = is_k8s
        self.k8s_config = k8s_config if k8s_config is not None else {}
        self.scale_server_flow_rate = scale_server_flow_rate
        self.acu2server_flow_ratio = acu2server_flow_ratio
        self.is_gpu = is_gpu
        self.refinement_level = int(refinement_level)
        self.location_in_mesh = location_in_mesh

        self.last_state_case = None
        self.object_mesh_index = read_object_mesh_index(room=self.room)
        self.openfoam_image = openfoam_image
        self._setup_default_backend()

    def _setup_default_backend(self) -> None:
        """Setup default backend
        geometry: Salome
        meshing: SnappyHexMesh
        solver: buoyantBoussinesqSimpleFoam/buoyantBoussinesqPimpleFoam/POD
        reduced-order solver: POD
        """
        if self.isk8s:
            self.k8s_config["k8s_resources"] = self.k8s_config["k8s_meshing_resources"]
            self.k8s_config["k8s_taint"] = self.k8s_config["k8s_cpu_taint"]
            self.mesh_backend = SnappyHexK8sBackend(
                process_num=self.mesh_process,
                k8s_config=self.k8s_config,
                is_gpu=self.is_gpu,
            )
            if self.steady:
                self.k8s_config["k8s_resources"] = self.k8s_config[
                    "k8s_solving_resources"
                ]
                if "k8s_gpu_taint" in self.k8s_config:
                    self.k8s_config["k8s_taint"] = self.k8s_config["k8s_gpu_taint"]
                self.solver_backend = SteadySolverK8sBackend(
                    process_num=self.solve_process,
                    k8s_config=self.k8s_config,
                    is_gpu=self.is_gpu,
                )
                # use reduced-order simulation if POD mode is provided
                if not self.run_cfd and self.pod_method is not None:
                    assert (
                        self.object_mesh_index is not None
                    ), "object mesh index is required for POD simulation"
                    self.pod_backend = PODK8SBackend.load(
                        self.room, self.object_mesh_index
                    )
            else:
                self.k8s_config["k8s_resources"] = self.k8s_config[
                    "k8s_solving_resources"
                ]
                self.k8s_config["k8s_taint"] = self.k8s_config["k8s_gpu_taint"]
                self.solver_backend = TransientSolverK8sBackend(
                    process_num=self.solve_process, is_gpu=self.is_gpu
                )
            if self.openfoam_image:
                self.solver_backend.docker_image = self.openfoam_image
                self.mesh_backend.docker_image = self.openfoam_image
        else:
            self.mesh_backend = SnappyHexBackend(
                self.docker_client, is_gpu=self.is_gpu
            )
            if self.steady:
                self.solver_backend = SteadySolverDockerBackend(
                    self.docker_client,
                    process_num=self.solve_process,
                    is_gpu=self.is_gpu,
                )
                # use reduced-order simulation if POD mode is provided
                if not self.run_cfd and self.pod_method is not None:
                    assert (
                        self.object_mesh_index is not None
                    ), "object mesh index is required for POD simulation"
                    self.pod_backend = PODDockerBackend.load(
                        self.room, self.object_mesh_index
                    )
            else:
                self.solver_backend = TransientSolverDockerBackend(
                    self.docker_client, process_num=self.solve_process
                )

    def mesh(self) -> None:
        """Mesh the geometry"""
        try:
            logger.info("start meshing geometry ...")
            self.mesh_backend.run(
                room=self.room,
                process_num=self.mesh_process,
                case_dir=config.cfd.case_dir,
                refinement_level=self.refinement_level,
                location_in_mesh=self.location_in_mesh
            )
        except Exception:
            raise MeshBuildError("Failed to mesh geometry")

    def solve(
        self,
        stream: bool = False,
    ) -> None:
        """Solve the simulation
        :param stream: whether to stream the output
        """
        try:
            logger.info("start running CFD solver ...")
            return self.solver_backend.run(
                room=self.room,
                process_num=self.solve_process,
                end_time=self.end_time,
                write_interval=self.write_interval,
                last_state_case=self.last_state_case,
                stream=stream,
            )
        except Exception:
            raise FoamSolveError("Failed to solve the simulation")

    def _update_acu_boundaries(
        self,
        supply_air_temperatures: Dict,
        supply_air_volume_flow_rates: Dict,
    ) -> None:
        """Update ACU boundaries
        supply_air_temperatures: supply air temperature for each ACU
        supply_air_volume_flow_rates: supply air volume flow rate for each ACU
        """
        for acu_uid, acu in self.room.constructions.acus.items():
            if supply_air_temperatures is not None:
                try:
                    acu.cooling.operating.supply_air_temperature = (
                        supply_air_temperatures[acu_uid]
                    )
                except KeyError:
                    logger.critical(f"ACU {acu_uid} supply air temperature is missing")
            if supply_air_volume_flow_rates is not None:
                try:
                    acu.cooling.operating.supply_air_volume_flow_rate = (
                        supply_air_volume_flow_rates[acu_uid]
                    )
                except KeyError:
                    logger.critical(f"ACU {acu_uid} volume flow rate is missing")

    def _update_server_boundaries(
        self,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
    ) -> None:
        """Update server boundaries
        server_powers: server power for each server
        server_volume_flow_rates: server volume flow rate for each server
        """
        def __update_server_boundaries(
            _rack: Rack,
        ) -> None:
            for server_uid, server in _rack.constructions.servers.items():
                if server_powers is not None:
                    try:
                        server.power.input_power = server_powers[server_uid]
                    except KeyError:
                        logger.critical(f"server {server_uid} power is missing")
                if server_volume_flow_rates is not None:
                    try:
                        server.cooling.volume_flow_rate = server_volume_flow_rates[
                            server_uid
                        ]
                    except KeyError:
                        logger.critical(
                            f"server {server_uid} volume flow rate is missing"
                        )

        if self.room.constructions.racks is not None:
            for rack_id, rack in self.room.constructions.racks.items():
                __update_server_boundaries(rack)
        if self.room.constructions.rows is not None:
            for row_id, row in self.room.constructions.rows.items():
                for rack_id, rack in row.constructions.racks.items():
                    __update_server_boundaries(rack)


    def update_boundary_conditions(
        self,
        supply_air_temperatures: Dict = None,
        supply_air_volume_flow_rates: Dict = None,
        server_powers: Dict = None,
        server_volume_flow_rates: Dict = None,
        **kwargs,
    ) -> None:
        """Update boundary conditions for ACUs and servers"""
        self._update_acu_boundaries(
            supply_air_temperatures, supply_air_volume_flow_rates
        )
        self._update_server_boundaries(server_powers, server_volume_flow_rates)

        # TODO: add support for dehumidifiers

    @property
    def format_boundary_conditions(self) -> Dict:
        """Format boundary conditions for ACUs and servers to be used in the API"""

        def _get_server_boundary_conditions(_server_id:str, _server, is_modulus):
            boundary_conditions["server_powers"][_server_id] = _server.power.input_power
            boundary_conditions["server_volume_flow_rates"][_server_id] = _server.volume_flow_rate
            if is_modulus:
                server_inlet_face_center, server_outlet_face_center, server_box_center = (
                    self.room.constructions.server_patch_positions(_server_id))
                boundary_conditions["server_inlet_face_center"][_server_id] = server_inlet_face_center
                boundary_conditions["server_outlet_face_center"][_server_id] = server_outlet_face_center

        boundary_conditions = {
            "supply_air_temperatures": {},
            "supply_air_volume_flow_rates": {},
            "acu_supply_face_center": {},
            "acu_return_face_center": {},
            "server_powers": {},
            "server_volume_flow_rates": {},
            "server_inlet_face_center": {},
            "server_outlet_face_center": {},
        } if self.is_modulus else {
            "supply_air_temperatures": {},
            "supply_air_volume_flow_rates": {},
            "server_powers": {},
            "server_volume_flow_rates": {},
        }

        for acu_id, acu in self.room.constructions.acus.items():

            boundary_conditions["supply_air_temperatures"][acu_id] = acu.cooling.operating.supply_air_temperature

            boundary_conditions["supply_air_volume_flow_rates"][acu_id] = (acu.cooling.operating
                                                                           .supply_air_volume_flow_rate)
            if self.is_modulus:
                acu_return_face_center, acu_supply_face_center, acu_box_center = self.room.constructions.acu_patch_positions(acu_id)
                boundary_conditions["acu_supply_face_center"][acu_id] = acu_supply_face_center
                boundary_conditions["acu_return_face_center"][acu_id] = acu_return_face_center

        if self.room.constructions.racks is not None:
            for rack_id, rack in self.room.constructions.racks.items():
                for server_id, server in rack.constructions.servers.items():
                    _get_server_boundary_conditions(
                        _server_id=server_id,
                        _server=server,
                        is_modulus=self.is_modulus,
                    )

        if self.room.constructions.rows is not None:
            for row in self.room.constructions.rows.values():
                for rack_id, rack in row.constructions.racks.items():
                    for server_id, server in rack.constructions.servers.items():
                        _get_server_boundary_conditions(
                            _server_id=server_id,
                            _server=server,
                            is_modulus=self.is_modulus,
                        )

        # TODO: add support for dehumidifiers

        return boundary_conditions

    def _scale_server_flow_rate(
        self,
        boundary_conditions: Dict,
        acu2server_flow_ratio: float = 0.9,
        expert_mode: bool = False,
    ) -> Dict:
        """
        scale total server flow rate as a ratio of total supply air flow rate
        """
        sum_acu_volume_flow_rate = sum(
            boundary_conditions["supply_air_volume_flow_rates"].values()
        )
        sum_server_volume_flow_rate = sum(
            boundary_conditions["server_volume_flow_rates"].values()
        )

        logger.info(f"sum acu flow rate before scaling: {sum_acu_volume_flow_rate}")
        logger.info(
            f"sum server flow rate before scaling: {sum_server_volume_flow_rate}"
        )

        scale_factor = (
            sum_acu_volume_flow_rate
            * acu2server_flow_ratio
            / sum_server_volume_flow_rate
        )
        # scale server flow rate
        for server_id, volume_flow_rate in boundary_conditions[
            "server_volume_flow_rates"
        ].items():
            boundary_conditions["server_volume_flow_rates"][server_id] = (
                volume_flow_rate * scale_factor
            )

        if self.room.constructions.racks is not None:
            for rack_id, rack in self.room.constructions.racks.items():
                for server_id, server in rack.constructions.servers.items():
                    if server.cooling.fan_type == "Variable":
                        server.cooling.volume_flow_rate_ratio *= scale_factor
                    if server.cooling.fan_type == "Fixed":
                        server.cooling.volume_flow_rate = boundary_conditions["server_volume_flow_rates"][server_id]

        if self.room.constructions.rows is not None:
            for row_id, row in self.room.constructions.rows.items():
                for rack_id, rack in row.constructions.racks.items():
                    for server_id, server in rack.constructions.servers.items():
                        if server.cooling.fan_type == "Variable":
                            server.cooling.volume_flow_rate_ratio *= scale_factor
                        if server.cooling.fan_type == "Fixed":
                            server.cooling.volume_flow_rate = boundary_conditions["server_volume_flow_rates"][server_id]

        sum_acu_volume_flow_rate_after = sum(
            boundary_conditions["supply_air_volume_flow_rates"].values()
        )
        sum_server_volume_flow_rate_after = sum(
            boundary_conditions["server_volume_flow_rates"].values()
        )

        logger.info(
            f"sum acu flow rate after scaling: {sum_acu_volume_flow_rate_after}"
        )
        logger.info(
            f"sum server flow rate after scaling: {sum_server_volume_flow_rate_after}"
        )
        if expert_mode:
            logger.info("please check the flow rates. Wait for 5 seconds...")
            time.sleep(5)

        return boundary_conditions

    @staticmethod
    def get_user_input():
        while True:
            user_input = input("Continue? (y/n): ")
            if user_input.strip().lower() == "y":
                logger.info("Continue simulation...")
                break
            elif user_input.strip().lower() == "n":
                logger.info("Unsatisfied results. Stop simulation and improve...")
                sys.exit()
            else:
                logger.info("Please enter correct words...")

    @staticmethod
    def mesh_check():

        data_path = config.cfd.case_dir.joinpath("case.foam")
        application_name = "paraview"
        system = platform.system()

        if system == "Windows":
            executable_extensions = [".exe"]

            # all drives
            partitions = psutil.disk_partitions()
            common_install_dirs = [partition.device[:2] for partition in partitions]

            # search for all drives
            valid_flag = False
            for install_dir in common_install_dirs:
                for root, dirs, files in os.walk(install_dir):
                    for file in files:
                        # check application name
                        if file.lower().startswith(application_name.lower()) and any(
                            file.endswith(ext) for ext in executable_extensions
                        ):
                            # get file path
                            file_path = os.path.join(root, file)
                            # try to open
                            try:
                                logger.info(
                                    f"Application '{application_name}' searched. Path{file_path}. Try..."
                                )
                                subprocess.run(
                                    [file_path, "--data", data_path], check=True
                                )
                                valid_flag = True
                                break
                            except Exception as e:
                                logger.info(
                                    f"Error occurred while starting {file_path}: {e}"
                                )
                                valid_flag = False
                    if valid_flag:
                        break
                if valid_flag:
                    break
            if not valid_flag:
                logger.error(
                    f"No application '{application_name}'. Please stop debugging and install..."
                )
                sys.exit()

        elif system == "Linux":
            try:
                command = ["whereis", "paraview"]
                result = subprocess.run(command, capture_output=True, text=True)
                path = result.stdout.strip().split(": ")[1].split()[0]
                logger.info(f"Application '{application_name}'. Try...")
                subprocess.run([path, data_path], capture_output=True, text=True)
                valid_flag = True
            except Exception as e:
                logger.info(f"Error occurred while starting {application_name}: {e}")
                valid_flag = False
            if not valid_flag:
                logger.error(
                    f"No application '{application_name}'. Please stop debugging and install..."
                )
                sys.exit()
        elif system == "Darwin":
            try:
                # Applications folder path
                apps_folder = "/Applications"
                app_found = False
                for file in os.listdir(apps_folder):
                    # Check if the file name contains the partial field
                    if application_name.lower() in file.lower() and file.endswith(
                        ".app"
                    ):
                        app_path = os.path.join(apps_folder, data_path)
                        # Open the application
                        subprocess.run(["open", app_path])
                        logger.info(f"Opened application: {file}")
                        app_found = True
                        break
                if not app_found:
                    logger.critical(f'No application containing "{application_name}" found')
            except Exception as e:
                logger.critical("An error occurred:", e)

    def _adjust_server(self, racks: Union[RackModel, RowRackModel], servers_input: OrderedDict, boundary_conditions: Dict):
        for rack_key, rack in racks.items():

            rack_slot_num = int(round(rack.geometry.size.z / RackModel.slot_height))
            server_slot_size = 4 if self.refinement_level == 0 else 2
            servers_num = math.ceil(rack_slot_num / server_slot_size)
            new_rack_servers = {f"{rack_key}_server_slot_{_*server_slot_size}":{} for _ in range(servers_num)}
            slot_to_new_slot = {slot_index: slot_index // server_slot_size for slot_index in range(rack_slot_num)}

            for server_key, server in rack.constructions.servers.items():

                slot_position = server.geometry.slot_position
                slot_occupation = server.geometry.slot_occupation
                occupied_slots = range(slot_position, slot_position + slot_occupation)
                new_slot_counts = {}

                for slot in occupied_slots:
                    if slot >= rack_slot_num:
                        continue  # Skip if slot index exceeds the total number of slots
                    new_slot_index = slot_to_new_slot[slot]
                    new_slot_counts.setdefault(new_slot_index, 0)
                    new_slot_counts[new_slot_index] += 1

                # Calculate the fraction of the server in each new slot
                for new_slot_index, count in new_slot_counts.items():
                    fraction = count / slot_occupation
                    new_rack_servers[f"{rack_key}_server_slot_{new_slot_index*server_slot_size}"].setdefault(server_key,
                                                                                                             0)
                    new_rack_servers[f"{rack_key}_server_slot_{new_slot_index*server_slot_size}"][server_key] = (
                        round(fraction, 4))

            servers = OrderedDict()
            for new_server_key, server in new_rack_servers.items():
                if bool(server):

                    # Calculate the total input power of the new server
                    input_power = 0
                    volume_flow_rates = 0

                    for server_key in server.keys():
                        input_power += self.room.inputs.servers[server_key].input_power * server[server_key]
                        volume_flow_rates += (boundary_conditions["server_volume_flow_rates"][server_key]
                                              * server[server_key])

                    servers_input[new_server_key] = ServerInputs()
                    servers_input[new_server_key].input_power = input_power

                    # Create a new server object
                    max_key = max(server, key=lambda k: server[k]*rack.constructions.servers[k].geometry.slot_occupation)
                    servers[new_server_key] = copy.deepcopy(rack.constructions.servers[max_key])
                    servers[new_server_key].uid = new_server_key
                    servers[new_server_key].geometry.slot_position = int(new_server_key.split("_")[-1])
                    servers[new_server_key].geometry.slot_occupation = server_slot_size
                    servers[new_server_key].volume_flow_rate = volume_flow_rates

            rack.constructions.servers = servers

    def run(
        self,
        case_idx: int = 1,
        episode_idx: int = None,
        save_mesh_index: bool = False,
        save_boundary_conditions: bool = False,
        save_simulation_results: bool = False,
        return_sensor_results: bool = False,
        expert_mode: bool = False,
        **boundary_conditions,
    ) -> Union[np.ndarray, torch.Tensor, Dict]:
        """Run the whole simulation: geometry -> mesh -> solve
        :param expert_mode: whether to do the step checking
        :param case_idx: case index for different simulation (default: 1)
        :param episode_idx: episode index for different simulation (default: None)
            only used for co-simulation
        :param save_mesh_index: whether to save the mesh index
        :param save_boundary_conditions: whether to save the boundary conditions
        :param save_simulation_results: whether to save the simulation results
        :param return_sensor_results: whether to return sensor results
        :param scale_server_flow_rate: whether to scale server flow rate
        :param acu2server_flow_ratio: ratio of total supply air flow rate to total server flow rate
        :param boundary_conditions: boundary conditions for simulation
           i.e., boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
            "supply_air_relative_humidities": {} # optional, only for dehumidifiers
            }
        :return: temperature fields (np.ndarray, torch.Tensor) or sensor measured results (Dict)
        """

        if boundary_conditions is not None:
            self.update_boundary_conditions(**boundary_conditions)
            boundary_conditions = self.format_boundary_conditions

        if self.scale_server_flow_rate:
            boundary_conditions = self._scale_server_flow_rate(
                boundary_conditions=boundary_conditions,
                acu2server_flow_ratio=self.acu2server_flow_ratio,
                expert_mode=expert_mode,
            )
            self.update_boundary_conditions(**boundary_conditions)

        for server_key, server in self.room.inputs.servers.items():
            if server.air_volume_flow_rate:
                boundary_conditions["server_volume_flow_rates"][server_key] = server.air_volume_flow_rate

        if self.refinement_level < 2:
            servers_input = OrderedDict()
            if self.room.constructions.rows is not None:
                for row_key, row in self.room.constructions.rows.items():
                    self._adjust_server(
                        racks=row.constructions.racks,
                        servers_input=servers_input,
                        boundary_conditions=boundary_conditions
                    )
            if self.room.constructions.racks is not None:
                self._adjust_server(
                    racks=self.room.constructions.racks,
                    servers_input=servers_input,
                    boundary_conditions=boundary_conditions
                )
            self.room.inputs.servers = servers_input
            boundary_conditions = self.format_boundary_conditions
            self.update_boundary_conditions(**boundary_conditions)
            del servers_input

        if self.is_modulus:
            case_dir = "log/modules_base"
            acus_dict = {
                "acu_supply_face_center": boundary_conditions["acu_supply_face_center"],
                "acu_return_face_center": boundary_conditions["acu_return_face_center"],
                "acu_supply_temperatures": boundary_conditions["supply_air_temperatures"],
                "acu_supply_flow_rates": boundary_conditions["supply_air_volume_flow_rates"],
            }
            servers_dict = {
                "server_inlet_face_center": boundary_conditions["server_inlet_face_center"],
                "server_outlet_face_center": boundary_conditions["server_outlet_face_center"],
                "server_powers": boundary_conditions["server_powers"],
                "server_supply_flow_rates": boundary_conditions["server_volume_flow_rates"],
            }

            def run_modules(case_dir, acus_dict, servers_dict):
                return case_dir, acus_dict, servers_dict

            return run_modules(case_dir, acus_dict, servers_dict)
        else:
            if self.pod_backend is not None and not self.run_cfd:
                # use reduced-order CFD simulation if POD backend is provided
                # and run_cfd flag is set to False
                assert self.object_mesh_index is not None, (
                    "object mesh index is not provided"
                    "please specify the index file path or read from the mesh directory"
                )
                temperature = self.pod_backend.run(
                    pod_method=self.pod_method,
                    **boundary_conditions,
                )
                p, p_rgh, u = None, None, None
            else:
                run_mesh = check_base_dir(
                    episode_idx=episode_idx,
                    case_idx=case_idx,
                )
                # step 1: mesh
                if run_mesh:
                    # use full-fledged CFD simulation
                    init_foam(is_gpu=self.is_gpu, process_num=self.mesh_process)
                    self.mesh()
                    if save_mesh_index:
                        if self.object_mesh_index is None:
                            self.object_mesh_index = calc_object_mesh_index(
                                room=self.room,
                                mesh_points=read_mesh_coordinates(),
                            )
                        save_json_file(
                            path=config.cfd.mesh_dir.joinpath("object_mesh_index.json"),
                            saved_dict=self.object_mesh_index,
                        )
                if expert_mode:
                    logger.info("Check mesh results...")
                    self.mesh_check()
                    self.get_user_input()

                # step 2: solve
                self.solve(stream=False)

                all_dirs = [d for d in os.listdir(config.cfd.case_dir)]
                largest_num = 0
                for dir_name in all_dirs:
                    try:
                        num = int(dir_name)
                        if num > largest_num:
                            largest_num = num
                    except ValueError:
                        pass
                self.last_state_case = (
                    config.cfd.case_dir.joinpath(str(largest_num))
                    if not self.steady
                    else None
                )

                # step 3: read results
                temperature = read_temperature(config.cfd.case_dir, str(largest_num))
                p = read_p(config.cfd.case_dir, str(largest_num))
                p_rgh = read_p_rgh(config.cfd.case_dir, str(largest_num))
                u = read_u(config.cfd.case_dir, str(largest_num))

                if not config.cfd.PRESERVE_FOAM_LOG and not run_mesh:
                    shutil.rmtree(config.cfd.case_dir)

            sensor_results = (
                read_sensor_results(
                    case=config.cfd.case_dir,
                    room=self.room,
                    object_mesh_index=self.object_mesh_index,
                    temperature=temperature,
                    p = p,
                    p_rgh = p_rgh,
                    u = u
                )
                if self.room.constructions.sensors
                else {}
            )

            if save_boundary_conditions:
                assert config.cfd.case_dir is not None
                save_json_file(
                    path=config.cfd.case_dir.joinpath("boundary_conditions.json"),
                    saved_dict=boundary_conditions,
                )

            if save_simulation_results:
                assert config.cfd.case_dir is not None
                save_json_file(
                    path=config.cfd.case_dir.joinpath("simulation_sensor_results.json"),
                    saved_dict=sensor_results,
                )
            return sensor_results if return_sensor_results else temperature
