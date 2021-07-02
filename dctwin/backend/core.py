import abc

from docker import DockerClient

from dctwin.models import Room


class Backend(abc.ABC):

    def __init__(self, client: DockerClient, dry_run: bool = False) -> None:
        self.client = client
        self.dry_run = dry_run

    @property
    @abc.abstractmethod
    def docker_image(self):
        pass

    @abc.abstractmethod
    def run(self, room: Room):
        pass
