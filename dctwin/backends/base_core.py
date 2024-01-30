from abc import ABC, abstractmethod
from typing import Any, Union
from pathlib import Path


class BaseBackend(ABC):
    """
    Abstract base class for DCTwin Backend. Both Backend and BackendK8s classes should inherit from this class.
    It provides common structure and functionality to support the simulation of various dockerized simulators (e.g., EnergyPlus, OpenFoam).
    """

    volume_data_dir = "/data"
    volume_geometry_dir = f"{volume_data_dir}/constant/triSurface"

    def __init__(self, process_num: int = 1, **kwargs) -> None:
        self.process_num = process_num
        self.container = None

    @property
    @abstractmethod
    def docker_image(self) -> str:
        """
        Abstract property to get the docker image.
        """
        pass

    @property
    @abstractmethod
    def command(self) -> Union[list, str]:
        """
        Abstract property to get the command to run in docker.
        """
        pass

    @abstractmethod
    def run(self, **kwargs) -> None:
        """
        Abstract method to run the simulation.
        """
        pass

    @abstractmethod
    def run_container(
        self,
        case_dir: Union[Path, str],
        environment: dict = {},
        working_dir: str = None,
        stream: bool = False,
        command: list = None,
        background: bool = False,
        **kwargs,
    ) -> None:
        """
        Abstract method to run a docker container.
        This method should be implemented in the child classes with specific functionality.
        """
        pass
