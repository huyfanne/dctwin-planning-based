from typing import Optional, Union
from pathlib import Path

import click
import docker

from dctwin.backend.foam.snappyhex import SnappyHexBackend
from dctwin.backend.foam.solver import SteadySolverBackend, TransientSolverBackend
from dctwin.backend.geometry.salome import SalomeBackend
from dctwin.config import environ
from dctwin.models import Room


class SimulationError(Exception):
    pass


class DCTwinManager:
    def __init__(
        self,
        docker_client: docker.DockerClient = None,
        data_dir: Union[str, Path] = None,
        mesh_process: int = 1,
        solve_process: int = 1,
        steady: bool = True,
    ):
        self.docker_client = docker_client if docker_client else docker.from_env()
        if data_dir is not None:
            environ.set_case_dir(data_dir)
        self.geometry_backend: Optional[SalomeBackend] = None
        self.mesh_backend: Optional[SnappyHexBackend] = None
        self.solver_backend: Union[
            None, TransientSolverBackend, SteadySolverBackend
        ] = None
        self.mesh_process = mesh_process
        self.solve_process = solve_process
        self.steady = steady
        self.setup_default_backend()

    def setup_default_backend(self):
        """Setup default backend
        geometry: Salome
        meshing: SnappyHexMesh
        solver: buoyantBoussinesqSimpleFoam/buoyantBoussinesqPimpleFoam
        """
        self.geometry_backend = SalomeBackend(self.docker_client)
        self.mesh_backend = SnappyHexBackend(
            self.docker_client, process_num=self.mesh_process
        )
        if self.steady:
            self.solver_backend = SteadySolverBackend(
                self.docker_client, process_num=self.solve_process
            )
        else:
            self.solver_backend = TransientSolverBackend(
                self.docker_client, process_num=self.solve_process
            )

    def build_geometry(self, room: Room, dry_run: bool = False):
        try:
            self.geometry_backend.run(room, dry_run)
        except Exception as e:
            click.echo("Failed to build geometry")
            click.echo(e)

    def mesh(
        self,
        room: Room,
        dry_run: bool = False,
        process_num: int = None,
        field_config: Optional[dict] = None,
    ):
        try:
            self.mesh_backend.run(
                room,
                dry_run=dry_run,
                process_num=process_num,
                field_config=field_config,
            )
        except Exception as e:
            click.echo("Failed to mesh")
            click.echo(e)

    def solve(
        self,
        room: Room,
        mesh_path=None,
        output_dir=None,
        dry_run: bool = False,
        process_num: int = None,
        end_time: int = None,
        write_interval: int = None,
        last_state_case: Union[Path, str] = None,
        stream: bool = False,
    ):
        try:
            return self.solver_backend.run(
                room,
                dry_run=dry_run,
                process_num=process_num,
                mesh_path=mesh_path,
                output_dir=output_dir,
                end_time=end_time,
                write_interval=write_interval,
                last_state_case=last_state_case,
                stream=stream,
            )
        except Exception as e:
            click.echo("Failed to solve")
            click.echo(e)

    def run_simulation(self, room: Room):
        self.build_geometry(room)
        self.mesh(room)
        self.solve(room)
