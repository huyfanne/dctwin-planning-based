import abc
from typing import Union

import click
from dctwin.config import environ
from dctwin.models import Room
from docker import DockerClient
from docker.errors import ContainerError


class Backend(abc.ABC):
    volume_data_dir = "/data"
    volume_geometry_dir = f"{volume_data_dir}/constant/triSurface"

    def __init__(self, client: DockerClient, process_num: int = 1) -> None:
        self.client = client
        self.process_num = process_num

    @property
    @abc.abstractmethod
    def docker_image(self):
        pass

    @property
    @abc.abstractmethod
    def command(self) -> Union[list, str]:
        pass

    @abc.abstractmethod
    def run(self, room: Room, dry_run: bool = None, process_num: int = None):
        pass

    def run_container(
        self,
        environment: dict = None,
        auto_remove: bool = True,
        user: int = None,
        working_dir: str = None,
        stream: bool = False,
    ) -> None:
        try:
            container = self.client.containers.run(
                self.docker_image,
                command=self.command,
                auto_remove=auto_remove,
                volumes={
                    str(environ.CASE_DIR): {
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
            )
            output_stream = container.logs(stream=True, follow=True)
            if stream:
                return output_stream
            else:
                for log in output_stream:
                    if environ.BACKEND_LOG_PRINT:
                        click.echo(log, nl=False)
        except ContainerError as e:
            click.echo(str(e.stderr))
            raise e
