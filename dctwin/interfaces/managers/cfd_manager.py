import shutil
from typing import Optional, Union, Dict
import numpy as np
import docker
import torch
from loguru import logger

from dctwin.backends import (
    SalomeBackend,
    SnappyHexBackend,
    SteadySolverBackend,
    TransientSolverBackend,
    PODBackend,
)

from .utils import (
    check_base_dir,
    read_object_mesh_index,
    read_mesh_coordinates,
    calc_object_mesh_index,
    save_json_file,
    read_temperature,
)

from dctwin.utils import config
from dctwin.utils.errors import (
    GeometryBuildError,
    MeshBuildError,
    FoamSolveError,
)
from dctwin.models import Room, Building


class CFDManager:
    """
    A manager for the whole CFD simulation for data hall thermal analysis
    :param building: a building object that contains all rooms
    :param mesh_process: number of cores for meshing
    :param solve_process: number of cores for solving
    :param steady: steady or transient simulation
    :param write_interval: write interval for simulation, can be set as 5, 10, 100, etc.
    :param end_time: end time for transient simulation, can be set as 50, 100, 500 etc. Normally 100-500 is enough.
    :param field_config: field configuration for meshing
    :param docker_client: docker client
    """
    def __init__(
        self,
        building: Building,
        room_id: str,
        mesh_process: int = 32,
        solve_process: int = 32,
        steady: bool = True,
        run_cfd: bool = True,
        write_interval: int = 50,
        end_time: int = 100,
        field_config: Dict = None,
        pod_method: str = "GP",
        docker_client: docker.DockerClient = None,
    ) -> None:
        self.docker_client = docker_client if docker_client else docker.from_env()
        self.geometry_backend: Optional[SalomeBackend] = None
        self.mesh_backend: Optional[SnappyHexBackend] = None
        self.solver_backend: Union[
            None, TransientSolverBackend, SteadySolverBackend
        ] = None
        self.pod_backend: Optional[PODBackend] = None

        self.building: Building = building
        self.room_id: str = room_id
        self.room: Room = building.constructions.rooms[room_id]
        self.steady = steady
        self.run_cfd = run_cfd
        self.mesh_process = mesh_process
        self.solve_process = solve_process
        self.write_interval = write_interval
        self.end_time = end_time
        self.field_config = field_config
        self.steady = steady
        self.pod_method = pod_method

        self.last_state_case = None
        self.object_mesh_index = read_object_mesh_index(room=self.room)
        self._setup_default_backend()

    def _setup_default_backend(self) -> None:
        """Setup default backend
        geometry: Salome
        meshing: SnappyHexMesh
        solver: buoyantBoussinesqSimpleFoam/buoyantBoussinesqPimpleFoam/POD
        """
        self.geometry_backend = SalomeBackend(self.docker_client)
        self.mesh_backend = SnappyHexBackend(
            self.docker_client, process_num=self.mesh_process
        )
        if self.steady:
            self.solver_backend = SteadySolverBackend(
                self.docker_client, process_num=self.solve_process
            )
            # use reduced-order simulation if POD mode is provided
            self.pod_backend = PODBackend.load()
        else:
            self.solver_backend = TransientSolverBackend(
                self.docker_client, process_num=self.solve_process
            )

    def _map_boundary_conditions_to_tensor(
        self,
        supply_air_temperatures: Dict,
        supply_air_volume_flow_rates: Dict,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
    ) -> Dict:
        """
        Map boundary conditions to tensor
        :param supply_air_temperatures: acu supply temperature dict
        :param supply_air_volume_flow_rates: acu volume flow rate dict
        :param server_powers: server heat loads dict
        :param server_volume_flow_rates: server volume flow rates dict
        """
        q_server, v_server, sp_acu, v_acu = [], [], [], []
        # parse the boundary conditions into torch.Tensor format
        for server_name, server_mesh_indices in self.object_mesh_index["servers"].items():
            q_server.append(server_powers[server_name])
            v_server.append(server_volume_flow_rates[server_name])

        for acu_name, acu_mesh_indices in self.object_mesh_index["acus"].items():
            sp_acu.append(supply_air_temperatures[acu_name])
            v_acu.append(supply_air_volume_flow_rates[acu_name])

        q_server = torch.tensor(q_server, dtype=torch.float32, requires_grad=False)
        v_server = torch.tensor(v_server, dtype=torch.float32, requires_grad=False)
        sp_acu = torch.tensor(sp_acu, dtype=torch.float32, requires_grad=False)
        v_acu = torch.tensor(v_acu, dtype=torch.float32, requires_grad=False)

        return {
            "server_powers": q_server,
            "server_volume_flow_rates": v_server,
            "supply_air_temperatures": sp_acu,
            "supply_air_volume_flow_rates": v_acu,
        }

    def build_geometry(self) -> None:
        """Build geometry from room model"""
        try:
            logger.info("start building geometry ...")
            self.geometry_backend.run(building=self.building, room_id=self.room_id)
        except Exception:
            raise GeometryBuildError("Failed to build geometry")

    def mesh(self) -> None:
        """Mesh the geometry
        """
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

    def run(
        self,
        case_idx: int = 1,
        episode_idx: int = None,
        save_mesh_index: bool = False,
        save_boundary_conditions: bool = False,
        **boundary_conditions
    ) -> Union[np.ndarray, torch.Tensor]:
        """Run the whole simulation: geometry -> mesh -> solve
        :param case_idx: case index for different simulation (default: 1)
        :param episode_idx: episode index for different simulation (default: None)
            only used for co-simulation
        :param save_mesh_index: whether to save the mesh index
        :param save_boundary_conditions: whether to save the boundary conditions
        :param boundary_conditions: boundary conditions for simulation
           i.e., boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
            }
        :return: temperature fields
        """
        if self.pod_backend is not None and not self.run_cfd:
            # use reduced-order CFD simulation if POD backend is provided and run_cfd flag is set
            assert self.object_mesh_index is not None, \
                "object mesh index is not provided， " \
                "please specify the index file path or read from the mesh directory"
            results = self.pod_backend.run(
                object_mesh_index=self.object_mesh_index,
                pod_method=self.pod_method,
                **self._map_boundary_conditions_to_tensor(**boundary_conditions)
            )
        else:
            # use full-fledged CFD simulation
            run_geometry, run_mesh = check_base_dir(
                episode_idx=episode_idx,
                case_idx=case_idx,
            )
            if run_geometry:
                self.build_geometry()
            if run_mesh:
                self.mesh()
                if save_mesh_index and self.object_mesh_index is None:
                    self.object_mesh_index = calc_object_mesh_index(
                        room=self.room, mesh_points=read_mesh_coordinates(),
                    )
                    save_json_file(
                        path=config.cfd.mesh_dir.joinpath("object_mesh_index.json"),
                        saved_dict=self.object_mesh_index,
                    )
            if boundary_conditions:
                self.room.update_boundary_conditions(**boundary_conditions)
            self.solve(stream=False)
            if save_boundary_conditions:
                save_json_file(
                    path=config.cfd.case_dir.joinpath("boundary_conditions.json"),
                    saved_dict=boundary_conditions,
                )
            self.last_state_case = config.cfd.case_dir.joinpath(str(self.end_time)) \
                if not self.steady else None
            results = read_temperature(config.cfd.case_dir, str(self.end_time))

            if not config.cfd.PRESERVE_FOAM_LOG and not run_mesh and not run_geometry:
                shutil.rmtree(config.cfd.case_dir)

        return results
