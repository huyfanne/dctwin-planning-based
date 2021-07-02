from typing import Optional

import docker

from dctwin.backend.foam.snappyhex import SnappyHexBackend
from dctwin.backend.geometry.salome import SalomeBackend
from dctwin.models import Room


class DCTwinManager:

    def __init__(self, docker_client: docker.DockerClient = None):
        self.docker_client = docker_client if docker_client else docker.from_env()
        self.geometry_backend: Optional[SalomeBackend] = None
        self.mesh_backend: Optional[SalomeBackend] = None
        self.solver_backend: Optional[SalomeBackend] = None
        self.setup_backend()

    def setup_backend(self):
        self.geometry_backend = SalomeBackend(self.docker_client)
        self.mesh_backend = SnappyHexBackend(self.docker_client)

    def run_simulation(self, room: Room):
        self.geometry_backend.run(room)
        self.mesh_backend.run(room)
