import shutil
from typing import Optional, Union, Dict
import numpy as np
import docker
import torch
from loguru import logger

from dctwin.backends import (
    SalomeBackend,
    SalomeBackendK8s,
    SnappyHexBackend,
    SnappyHexBackendK8s,
    SteadySolverBackend,
    SteadySolverBackendK8s,
    TransientSolverBackend,
    TransientSolverBackendK8s,
    PODBackend,
    PODBackendK8s,
)

from .utils import (
    check_base_dir,
    read_object_mesh_index,
    read_mesh_coordinates,
    calc_object_mesh_index,
    save_json_file,
    read_temperature,
    read_sensor_temperature_results,
)

from dctwin.utils import config
from dctwin.utils.errors import (
    GeometryBuildError,
    MeshBuildError,
    FoamSolveError,
)
from dctwin.models import Room


class CFDManager:
    """
    A manager for the whole CFD simulation for data hall thermal analysis
    the workflow includes:
    1. build geometry
    2. mesh geometry
    3. solve steady or transient simulation
    4. post process results

    :param room: a room object that contains all rooms
    :param mesh_process: number of CPU cores for meshing
    :param solve_process: number of CPU cores for solving
    :param steady: use steady or transient simulation
    :param write_interval: data write interval for simulation, can be set as 5, 10, 100, etc.
    :param end_time: end step for steady simulation, can be set as 50, 100, 150, etc. Normally 100-500 is enough.
    :param field_config: field configuration for meshing
    :param pod_method: POD method, can be GP, Flux, or GP-Flux
    :param docker_client: docker client
    """

    def __init__(
        self,
        room: Room,
        mesh_process: int = 32,
        solve_process: int = 32,
        steady: bool = True,
        run_cfd: bool = True,
        write_interval: int = 50,
        end_time: int = 100,
        field_config: Dict = None,
        pod_method: str = "GP",
        docker_client: docker.DockerClient = None,
        is_k8s: bool = False,
        k8s_config: Dict = {},
        scale_server_flow_rate: bool = False,
        acu2server_flow_ratio: float = 0.8,
    ) -> None:
        if not is_k8s:
            self.docker_client = docker_client if docker_client else docker.from_env()
        self.geometry_backend: Optional[Union[SalomeBackend, SalomeBackendK8s]] = None
        self.mesh_backend: Optional[Union[SnappyHexBackend, SnappyHexBackendK8s]] = None
        self.solver_backend: Union[
            None,
            TransientSolverBackend,
            SteadySolverBackend,
            TransientSolverBackendK8s,
            SteadySolverBackendK8s,
        ] = None
        self.pod_backend: Optional[Union[PODBackend, PODBackendK8s]] = None

        self.room: Room = room
        self.steady = steady
        self.run_cfd = run_cfd
        self.mesh_process = mesh_process
        self.solve_process = solve_process
        self.write_interval = write_interval
        self.end_time = end_time
        self.field_config = field_config
        self.steady = steady
        self.pod_method = pod_method
        self.isk8s = is_k8s
        self.k8s_config = k8s_config
        self.scale_server_flow_rate = scale_server_flow_rate
        self.acu2server_flow_ratio = acu2server_flow_ratio

        self.last_state_case = None
        self.object_mesh_index = read_object_mesh_index(room=self.room)
        self._setup_default_backend()

    def _setup_default_backend(self) -> None:
        """Setup default backend
        geometry: Salome
        meshing: SnappyHexMesh
        solver: buoyantBoussinesqSimpleFoam/buoyantBoussinesqPimpleFoam/POD
        reduced-order solver: POD
        """
        if self.isk8s:
            self.geometry_backend = SalomeBackendK8s(k8s_config=self.k8s_config)
            self.mesh_backend = SnappyHexBackendK8s(
                process_num=self.mesh_process, k8s_config=self.k8s_config
            )
            if self.steady:
                self.solver_backend = SteadySolverBackendK8s(
                    process_num=self.solve_process,
                    k8s_config=self.k8s_config,
                )
                # use reduced-order simulation if POD mode is provided
                if not self.run_cfd and self.pod_method is not None:
                    assert (
                        self.object_mesh_index is not None
                    ), "object mesh index is required for POD simulation"
                    self.pod_backend = PODBackendK8s.load(
                        self.room, self.object_mesh_index
                    )
            else:
                self.solver_backend = TransientSolverBackendK8s(
                    process_num=self.solve_process
                )
        else:
            self.geometry_backend = SalomeBackend(self.docker_client)
            self.mesh_backend = SnappyHexBackend(
                self.docker_client, process_num=self.mesh_process
            )
            if self.steady:
                self.solver_backend = SteadySolverBackend(
                    self.docker_client, process_num=self.solve_process
                )
                # use reduced-order simulation if POD mode is provided
                if not self.run_cfd and self.pod_method is not None:
                    assert (
                        self.object_mesh_index is not None
                    ), "object mesh index is required for POD simulation"
                    self.pod_backend = PODBackend.load(
                        self.room, self.object_mesh_index
                    )
            else:
                self.solver_backend = TransientSolverBackend(
                    self.docker_client, process_num=self.solve_process
                )

    def build_geometry(self) -> None:
        """Build geometry from room model"""
        try:
            logger.info("start building geometry ...")
            self.geometry_backend.run(room=self.room)
        except Exception:
            raise GeometryBuildError("Failed to build geometry")

    def mesh(self) -> None:
        """Mesh the geometry"""
        try:
            logger.info("start meshing geometry ...")
            self.mesh_backend.run(
                room=self.room,
                process_num=self.mesh_process,
                field_config=self.field_config,
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
                    acu.cooling.supply_air_temperature = supply_air_temperatures[
                        acu_uid
                    ]
                except KeyError:
                    logger.critical(f"ACU {acu_uid} supply air temperature is missing")
            if supply_air_volume_flow_rates is not None:
                try:
                    acu.cooling.supply_air_volume_flow_rate = (
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
        for rack_id, rack in self.room.constructions.racks.items():
            for server_uid, server in rack.constructions.servers.items():
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

    def update_boundary_conditions(
        self,
        supply_air_temperatures: Dict = None,
        supply_air_volume_flow_rates: Dict = None,
        server_powers: Dict = None,
        server_volume_flow_rates: Dict = None,
    ) -> None:
        """Update boundary conditions for ACUs and servers"""
        self._update_acu_boundaries(
            supply_air_temperatures, supply_air_volume_flow_rates
        )
        self._update_server_boundaries(server_powers, server_volume_flow_rates)

    @property
    def format_boundary_conditions(self) -> Dict:
        """Format boundary conditions for ACUs and servers to be used in the API"""
        boundary_conditions = {
            "supply_air_temperatures": {},
            "supply_air_volume_flow_rates": {},
            "server_powers": {},
            "server_volume_flow_rates": {},
        }
        for acu_id, acu in self.room.constructions.acus.items():
            boundary_conditions["supply_air_temperatures"][
                acu_id
            ] = acu.cooling.supply_air_temperature
            boundary_conditions["supply_air_volume_flow_rates"][
                acu_id
            ] = acu.cooling.supply_air_volume_flow_rate

        for rack_id, rack in self.room.constructions.racks.items():
            for server_id, server in rack.constructions.servers.items():
                boundary_conditions["server_powers"][
                    server_id
                ] = server.power.input_power
                boundary_conditions["server_volume_flow_rates"][
                    server_id
                ] = server.volume_flow_rate

        return boundary_conditions

    @staticmethod
    def _scale_server_flow_rate(
        boundary_conditions: Dict, acu2server_flow_ratio: float = 0.8
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
        return boundary_conditions

    def run(
        self,
        case_idx: int = 1,
        episode_idx: int = None,
        save_mesh_index: bool = False,
        save_boundary_conditions: bool = False,
        save_simulation_results: bool = False,
        return_sensor_results: bool = False,
        **boundary_conditions,
    ) -> Union[np.ndarray, torch.Tensor, Dict]:
        """Run the whole simulation: geometry -> mesh -> solve
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
            )

        if self.pod_backend is not None and not self.run_cfd:
            # use reduced-order CFD simulation if POD backend is provided
            # and run_cfd flag is set to False
            assert self.object_mesh_index is not None, (
                "object mesh index is not provided， "
                "please specify the index file path or read from the mesh directory"
            )
            results = self.pod_backend.run(
                pod_method=self.pod_method,
                **boundary_conditions,
            )
        else:
            run_geometry, run_mesh = check_base_dir(
                episode_idx=episode_idx,
                case_idx=case_idx,
            )
            # use full-fledged CFD simulation
            # step 1: build geometry
            if run_geometry:
                self.build_geometry()
            # step 2: mesh geometry
            if run_mesh:
                self.mesh()
                if save_mesh_index and self.object_mesh_index is None:
                    self.object_mesh_index = calc_object_mesh_index(
                        room=self.room,
                        mesh_points=read_mesh_coordinates(),
                    )
                    save_json_file(
                        path=config.cfd.mesh_dir.joinpath("object_mesh_index.json"),
                        saved_dict=self.object_mesh_index,
                    )
            # step 3: solve
            self.solve(stream=False)

            self.last_state_case = (
                config.cfd.case_dir.joinpath(str(self.end_time))
                if not self.steady
                else None
            )
            # step 4: read results
            results = read_temperature(config.cfd.case_dir, str(self.end_time))

            if not config.cfd.PRESERVE_FOAM_LOG and not run_mesh and not run_geometry:
                shutil.rmtree(config.cfd.case_dir)

        sensor_results = (
            read_sensor_temperature_results(
                case=config.cfd.case_dir,
                room=self.room,
                object_mesh_index=self.object_mesh_index,
                temperature=results,
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

        return sensor_results if return_sensor_results else results
