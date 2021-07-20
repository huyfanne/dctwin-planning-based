from typing import Optional

import docker

from dctwin.backend.foam.snappyhex import SnappyHexBackend
from dctwin.backend.foam.steady_solver import SteadySolverBackend
from dctwin.backend.geometry.salome import SalomeBackend
from dctwin.models import Room
from dctwin.config import environ


class SimulationError(Exception):
    pass


class DCTwinManager:
    def __init__(self,
                 docker_client: docker.DockerClient = None,
                 data_dir: Optional[str] = None,
                 mesh_process: int = 1,
                 solve_process: int = 1):
        self.docker_client = docker_client if docker_client else docker.from_env()
        if data_dir is not None:
            environ.set_case_dir(data_dir)
        self.geometry_backend: Optional[SalomeBackend] = None
        self.mesh_backend: Optional[SnappyHexBackend] = None
        self.solver_backend: Optional[SteadySolverBackend] = None
        self.mesh_process = mesh_process
        self.solve_process = solve_process
        self.setup_backend()

    def setup_backend(self):
        self.geometry_backend = SalomeBackend(self.docker_client)
        self.mesh_backend = SnappyHexBackend(self.docker_client,
                                             process_num=self.mesh_process)
        self.solver_backend = SteadySolverBackend(
            self.docker_client, process_num=self.solve_process)

    def run_simulation(self, room: Room) -> bool:
        try:
            self.geometry_backend.run(room)
            self.mesh_backend.run(room)
            self.solver_backend.run(room)
        except Exception as e:
            # Todo: use exact exceptions
            return False
        else:
            return True
