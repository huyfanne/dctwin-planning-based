import abc
from typing import Union

import click
from docker import DockerClient
from docker.errors import ContainerError

from dctwin.config import environ
from dctwin.models import Room


class Backend(abc.ABC):
    data_dir = '/data'
    geometry_dir = '/data/constant/triSurface'

    def __init__(
        self, client: DockerClient, dry_run: bool = False, process_num: int = 1
    ) -> None:
        self.client = client
        self.dry_run = dry_run
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
    def run(self, room: Room):
        pass

    def run_container(
        self,
        environment: dict = None,
        auto_remove: bool = True,
        working_dir: str = None,
    ) -> None:
        try:
            container = self.client.containers.run(
                self.docker_image,
                command=self.command,
                auto_remove=auto_remove,
                volumes={
                    str(environ.CASE_DIR): {
                        'bind': self.data_dir,
                        'mode': 'rw',
                    },
                    str(environ.GEOMETRY_DIR): {
                        'bind': self.geometry_dir,
                        'mode': 'rw',
                    },
                },
                environment=environment,
                working_dir=working_dir if working_dir is not None else self.data_dir,
                detach=True,
            )
            stream = container.logs(stream=True, follow=True)
            for log in stream:
                click.echo(log, nl=False)
        except ContainerError as e:
            click.echo(str(e.stderr))
            raise e
