import abc
from typing import Union

import click
from docker import DockerClient
from docker.errors import ContainerError

from dctwin.config import environ
from dctwin.models import Room


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
                },
                user=user,
                environment=environment,
                working_dir=working_dir
                if working_dir is not None
                else self.volume_data_dir,
                detach=True,
            )
            stream = container.logs(stream=True, follow=True)
            for log in stream:
                click.echo(log, nl=False)
        except ContainerError as e:
            click.echo(str(e.stderr))
            raise e
