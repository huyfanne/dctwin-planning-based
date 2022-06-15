import os
from pathlib import Path

import click

from dctwin.backend import template_env
from dctwin.backend.core import Backend
from dctwin.config import environ
from dctwin.models.constructions import Room

from docker.errors import ImageNotFound


class SalomeBackend(Backend):
    docker_image = "charact3/salome-9"

    def run(self, room: Room, dry_run: bool = False):
        self._pre_process(room)
        if not dry_run:
            self._run_backend()
        self._post_process()

    @property
    def command(self):
        return [
            "bash",
            "-c",
            "salome start -t geometry_script.py "
            f"&& chown -R {os.getuid}:{os.getgid} {self.volume_data_dir}",
        ]

    def _pre_process(self, room: Room):
        """Prepare files needed"""
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            click.echo("Salome image not existed, try to pull...")
            self.client.images.pull(self.docker_image)

        environ.CASE_DIR.mkdir(parents=True, exist_ok=True)
        environ.geometry_dir.mkdir(parents=True, exist_ok=True)

        geometry_script = Path(environ.geometry_dir, "geometry_script.py")
        geometry_description = Path(environ.geometry_dir, "geometry.json")
        with open(geometry_description, "w") as f:
            f.write(room.json())
        template = template_env.get_template("salome/geometry_script.py")
        with open(geometry_script, "w") as f:
            f.write(template.render())
        self._clean_files = [geometry_script, geometry_description]

    def _post_process(self):
        for file in self._clean_files:
            file.unlink()

    def _run_backend(self):
        working_path = self.volume_geometry_dir
        geometry_file = f"{working_path}/geometry.json"
        self.run_container(
            environment={
                "SRC_PATH": geometry_file,
                "OUTPUT_PATH": working_path,
            },
            working_dir=working_path,
        )
        click.echo("***** Geometry finished *****\n\n")
