import os
from pathlib import Path

from loguru import logger
from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s
from dctwin.models import Room
from dctwin.utils import template_env, config


class SalomeBackendMixin:
    """
    A class to manage the geometry generation using Salome.
    """

    docker_image = "ghcr.io/cap-dcwiz/salome-9-debian10:latest"

    def run(self, room: Room):
        self._pre_process(room)
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

    def _pre_process(self, room: Room):
        """Prepare files needed"""
        config.cfd.case_dir.mkdir(parents=True, exist_ok=True)
        config.cfd.geometry_dir.mkdir(parents=True, exist_ok=True)

        geometry_script = Path(config.cfd.geometry_dir, "geometry_script.py")
        geometry_description = Path(config.cfd.geometry_dir, "geometry.json")
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
        host_path = os.environ.get("HOST_PATH", None)
        if host_path is not None:
            # concatenate the log path in Docker container with external host path
            log_index = config.cfd.case_dir.parts.index("log")
            case_dir = "/".join(config.cfd.case_dir.parts[log_index:])
            case_dir = Path(host_path).joinpath(case_dir)
            logger.info(f"Concatenated Case Directory: {case_dir}")
        else:
            case_dir = config.cfd.case_dir

        self.run_container(
            case_dir=case_dir,
            environment={
                "SRC_PATH": geometry_file,
                "OUTPUT_PATH": working_path,
            },
            working_dir=working_path,
        )

        logger.info("***** Geometry finished *****\n\n")


class SalomeBackend(SalomeBackendMixin, Backend):
    pass


class SalomeBackendK8s(SalomeBackendMixin, BackendK8s):
    pass
