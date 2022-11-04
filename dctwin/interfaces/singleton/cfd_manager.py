import shutil
from typing import Optional, Union, Dict
import numpy as np
import docker
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
from dctwin.models import Room
from dctwin.backends.foam.parser import RoomParser


class CFDManager:
    """
    A manager for the whole CFD simulation for data hall thermal analysis

    :param room: room model
    :param mesh_process: number of cores for meshing
    :param solve_process: number of cores for solving
    :param steady: steady or transient simulation
    :param write_interval: write interval for simulation, can be set as 5, 10, 100, etc.
    :param end_time: end time for transient simulation, can be set as 50, 100, 500 etc. Normally 100-500 is enough.
    :param field_config: field configuration for meshing
    :param print_backend_log: whether to print the backend log
    :param docker_client: docker client

    """
    def __init__(
        self,
        room: Room,
        mesh_process: int = 8,
        solve_process: int = 8,
        steady: bool = True,
        write_interval: int = 50,
        end_time: int = 100,
        field_config: Dict = None,
        print_backend_log: bool = False,
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

        self.room = room
        self.steady = steady
        self.mesh_process = mesh_process
        self.solve_process = solve_process
        self.write_interval = write_interval
        self.end_time = end_time
        self.field_config = field_config
        config.BACKEND_LOG_PRINT = print_backend_log
        self.steady = steady
        self.pod_method = pod_method

        self.last_state_case = None
        self.object_mesh_index = read_object_mesh_index()

        self.parser = RoomParser(room=room)
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

    def build_geometry(self, dry_run: bool = False) -> None:
        """Build geometry from room model"""
        try:
            logger.info("start building geometry ...")
            self.geometry_backend.run(room=self.room, dry_run=dry_run)
        except Exception:
            logger.critical("Failed to build geometry")
            exit(-1)

    def mesh(self, dry_run: bool = False) -> None:
        """Mesh the geometry
        """
        try:
            logger.info("start meshing geometry ...")
            self.mesh_backend.run(
                room=self.room,
                process_num=self.mesh_process,
                field_config=self.field_config,
                dry_run=dry_run,
            )
        except Exception:
            logger.critical("Failed to mesh")
            exit(-1)

    def solve(
        self,
        dry_run: bool = False,
        stream: bool = False,
    ) -> None:
        """Solve the simulation
        :param dry_run: whether to dry run
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
                dry_run=dry_run,
                stream=stream,
            )
        except Exception:
            logger.critical("Failed to solve")
            exit(-1)

    def run(
        self,
        case_index: int = 1,
        episode_index: int = None,
        dry_run: bool = False,
        remove_foam_log: bool = True,
        save_mesh_index: bool = True,
        save_boundary_conditions: bool = False,
        **boundary_conditions
    ) -> np.ndarray:
        """Run the whole simulation: geometry -> mesh -> solve
        :param case_index: case index for different simulation (default: 1)
        :param episode_index: episode index for different simulation (default: None)
            only used for co-simulation
        :param dry_run: whether to dry run
        :param remove_foam_log: whether to remove the log of OpenFOAM
        :param save_mesh_index: whether to save the mesh index
        :param save_boundary_conditions: whether to save the boundary conditions
        :param boundary_conditions: boundary conditions for simulation
           e.g., boundary_conditions = {
            "crac_setpoints": {}, "crac_flow_rates": {},
            "server_powers": {}, "server_flow_rates": {}
            }

        :return: temperature fields
        """
        if self.pod_backend is not None:
            # use reduced-order CFD simulation if POD backend is provided
            assert self.object_mesh_index is not None, \
                "object mesh index is not provided， " \
                "please specify the index file path or read from the mesh directory"
            results = self.pod_backend.run(
                object_mesh_index=self.object_mesh_index,
                pod_method=self.pod_method,
                **boundary_conditions
            )

        else:
            # use full-fledged CFD simulation
            run_geometry, run_mesh = check_base_dir(
                episode_idx=episode_index,
                case_index=case_index
            )
            if run_geometry:
                self.build_geometry(dry_run=dry_run)
            if run_mesh:
                self.mesh(dry_run=dry_run)
                if save_mesh_index and self.object_mesh_index is None:
                    self.object_mesh_index = calc_object_mesh_index(
                        room=self.room, mesh_points=read_mesh_coordinates(),
                    )
                    save_json_file(
                        path=config.cfd.mesh_dir.joinpath("object_mesh_index.json"),
                        saved_dict=self.object_mesh_index,
                    )
            if boundary_conditions:
                self.parser.update_boundary_conditions(**boundary_conditions)
                if save_boundary_conditions:
                    save_json_file(
                        path=config.CASE_DIR.joinpath("boundary_conditions.json"),
                        saved_dict=boundary_conditions,
                    )
            self.solve(dry_run=dry_run, stream=False)
            self.last_state_case = config.CASE_DIR.joinpath(str(self.end_time)) \
                if not self.steady else None
            results = read_temperature(config.CASE_DIR, str(self.end_time))

            if remove_foam_log and not run_mesh and not run_geometry:
                shutil.rmtree(config.CASE_DIR)

        return results
