from pathlib import Path

from loguru import logger
from typing import Union

from docker import DockerClient, from_env
from docker.errors import ContainerError, ImageNotFound

from dctwin.utils import config
from dctwin.backends.base_core import BaseBackend


class Backend(BaseBackend):
    """
    Base class for DCTwin Backend. All backend should inherit this class.
    The Backend is to support the simulation of various simulators (EnergyPlus, OpenFoam, etc.) which is dockerized.
    It mainly takes care of the following tasks:
    1. Check the docker image of specific simulator
    2. Run the docker container of specific simulator

    :param client: docker client
    :param process_num: number of cores for simulation
    """

    def __init__(self, client: DockerClient = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.client = client
        if self.client is None:
            self.client = from_env()

    def check_image(self) -> None:
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            logger.info(
                f"docker image ({self.docker_image}) not existed, try to pull ..."
            )
            self.client.images.pull(self.docker_image)

    def run_container(
        self,
        case_dir: Union[Path, str],
        environment: dict = None,
        auto_remove: bool = True,
        user: int = None,
        working_dir: str = None,
        stream: bool = False,
        command: list = None,
        background: bool = False,
        **kwargs,
    ) -> None:
        command = self.command if command is None else command
        logger.info(f"docker mount: {case_dir}")
        logger.info("docker run: " + (" ".join(command)))
        self.check_image()
        try:
            self.client.close()
            self.container = self.client.containers.run(
                self.docker_image,
                command=command,
                auto_remove=auto_remove,
                volumes={
                    str(case_dir): {
                        "bind": self.volume_data_dir,
                        "mode": "rw",
                    },
                    "/etc/passwd": {
                        "bind": "/etc/passwd",
                        "mode": "ro",
                    },
                },
                user=user,
                environment=environment,
                working_dir=working_dir
                if working_dir is not None
                else self.volume_data_dir,
                detach=True,
                **kwargs,
            )
            if background:
                return None
            output_stream = self.container.logs(stream=True, follow=True)
            # do not change this container_id log, the worker are depending on this to get the container id
            logger.info(f"container_id: {self.container.id}")
            if stream:
                return output_stream
            else:
                for log in output_stream:
                    if config.BACKEND_LOG_PRINT:
                        logger.info(log.decode("utf-8").strip())
        except ContainerError as e:
            logger.info(str(e.stderr))
            raise e
