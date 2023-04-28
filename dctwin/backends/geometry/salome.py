import os
from pathlib import Path

from loguru import logger
from dctwin.backends.core import Backend
from dctwin.models import Building
from dctwin.utils import template_env, config


class SalomeBackend(Backend):
    """
    A class to manage the geometry generation using Salome.
    """
    docker_image = "ghcr.io/cap-dcwiz/salome-9-debian10:latest"

    def run(self, building: Building, room_id: str = None):
        self._pre_process(building, room_id=room_id)
        if not config.cfd.dry_run:
            self._run_backend()
        self._post_process()

    @property
    def command(self):
        return [
            "bash",
            "-c",
            "salome start -t geometry_script.py "
            f"&& chown -R {os.getuid()}:{os.getgid()} {self.volume_data_dir}",
        ]

    def _pre_process(self, building: Building, room_id: str):
        """Prepare files needed"""
        config.cfd.case_dir.mkdir(parents=True, exist_ok=True)
        config.cfd.geometry_dir.mkdir(parents=True, exist_ok=True)

        geometry_script = Path(config.cfd.geometry_dir, "geometry_script.py")
        geometry_description = Path(config.cfd.geometry_dir, "geometry.json")
        with open(geometry_description, "w") as f:
            f.write(building.json())
        template = template_env.get_template("salome/geometry_script.py")
        with open(geometry_script, "w") as f:
            f.write(template.render())
        self._room_id = room_id
        self._clean_files = [geometry_script, geometry_description]

    def _post_process(self):
        for file in self._clean_files:
            file.unlink()

    def _run_backend(self):
        working_path = self.volume_geometry_dir
        geometry_file = f"{working_path}/geometry.json"
        self.run_container(
            case_dir=config.cfd.case_dir,
            environment={
                "SRC_PATH": geometry_file,
                "OUTPUT_PATH": working_path,
                "ROOM_ID": self._room_id,
            },
            working_dir=working_path,
        )
        logger.info("***** Geometry finished *****\n\n")
