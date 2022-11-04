import os
import csv
import typing
from typing import TextIO, Union
from .errors import EplusConfigError, PODConfigError

import sys
import shutil

from .dt_engine_pb2 import DTEngineConfig, LoggingConfig

from google.protobuf import text_format
from loguru import logger

from pathlib import Path
import datetime


class EplusConfig:
    """EnergyPlus configuration"""
    def __init__(self, base_config) -> None:
        self.base_env: Config = base_config
        self.output_path: Path = os.environ.get("EPLUS_OUTPUT_PATH", "")
        self.idf_file: Path = Path(os.environ.get("EPLUS_IDF_FILE", ""))
        self.weather_file: Path = os.environ.get("EPLUS_WEATHER", "")
        self.engine_config_file: Path = Path(
            os.environ.get("EPLUS_ENGINE_CONFIG", "engine.prototxt")
        )

    def __setattr__(self, __name: str, __value: typing.Any) -> None:
        value = __value
        if __name in ("idf_file", "weather_file", "engine_config_file"):
            value = Path(__value)
        super().__setattr__(__name, value)

    def check_idf(self):
        if not self.idf_file.exists():
            raise EplusConfigError(f"idf file not exists: {self.idf_file}")

    def check_weather(self):
        if not self.weather_file.exists():
            raise EplusConfigError(f"weather file not exists: {self.weather_file}")


class CFDConfig:
    """CFD configuration"""
    def __init__(self, base_config) -> None:
        self.base_config: Config = base_config
        self.geometry_file = Path(os.environ.get("GEOMETRY_FILE", ""))
        self.mesh_dir: Path = Path(os.environ.get("MESH_DIR", ""))
        self.object_mesh_index: Path = Path(os.environ.get("OBJECT_MESH_INDEX", "object_mesh_index.json"))
        self.pod_dir: Path = Path(os.environ.get("POD_DIR", ""))
        self.num_modes: int = os.environ.get("NUM_MODES", 5)

        self.file_handler: TextIO = TextIO()
        self.log_handler: csv.DictWriter = csv.DictWriter(
            self.file_handler, fieldnames=["time", "mode", "value"]
        )

    def __setattr__(self, __name: str, __value: typing.Any) -> None:
        value = __value
        if __name in ("mesh_dir", "pod+dir", "object_mesh_index"):
            value = Path(__value)
        super().__setattr__(__name, value)

    def check_object_mesh_index(self):
        if not self.object_mesh_index.exists():
            raise PODConfigError(f"invalid object mesh index file: {self.object_mesh_index}")

    def check_mesh(self):
        if not self.mesh_dir.exists():
            raise PODConfigError(f"invalid mesh directory: {self.mesh_dir}")

    def check_pod(self):
        if not self.pod_dir.exists():
            raise PODConfigError(f"invalid pod directory: {self.pod_dir}")


class CoSimConfig:
    """Co-simulation configuration"""
    def __init__(self, base_config) -> None:
        self.base_config: Config = base_config
        self.idf2room_map: Path = Path(os.environ.get("MAP_FILE", ""))
        self.timestamp: datetime.datetime = os.environ.get(
            "TIME_STEP", datetime.datetime.now())  # time step to sync CFD and Eplus

    def check_map_file(self):
        if not self.idf2room_map.exists():
            raise EplusConfigError(f"invalid map file: {self.idf2room_map}")


class Config:
    """Base configuration
    :param env: environment variables
    :param base_size: base size of the meshing, default 0.2
    """
    CASE_DIR: Path
    BACKEND_LOG_PRINT: bool
    SOLVER_TURBULENCE: bool

    def __init__(self, env: typing.MutableMapping = os.environ, base_size: float = 0.2):
        self._environ = env
        # directory for experiment log, should be set by the user
        self.LOG_DIR = self._environ.get("LOG_DIR", Path("log").absolute())
        # directory for each simulation case or episode, subfolder of the log directory
        self.CASE_DIR = self._environ.get("CASE_DIR", Path("log/case").absolute())
        # backend
        self.BACKEND_LOG_PRINT = (
            self._environ.get("BACKEND_LOG_PRINT", "true").lower() == "true"
        )
        # solver
        self.SOLVER_TURBULENCE = (
            self._environ.get("SOLVER_TURBULENCE", "true").lower() == "true"
        )
        self.base_size: float = base_size

        self.eplus = EplusConfig(self)
        self.cfd = CFDConfig(self)
        self.co_sim = CoSimConfig(self)

    def set_log_dir(self, log_dir: typing.Union[str, Path]) -> None:
        self.LOG_DIR = Path(log_dir)

    def set_case_dir(self, case_dir: typing.Union[str, Path]) -> None:
        self.CASE_DIR = Path(case_dir)

    @property
    def geometry_dir(self):
        return Path(self.CASE_DIR, "constant/triSurface")


config = Config()


def read_engine_config(
    engine_config: str = "engine.prototxt"
) -> DTEngineConfig:
    """Read the proto engine configuration file.
    """
    # noinspection PyBroadException
    try:
        with open(engine_config, 'r') as f:
            dt_config = text_format.Parse(
                text=f.read(),
                message=DTEngineConfig(),
            )
        return dt_config
    except Exception:
        logger.exception(
            "Failed to parse engine configuration"
        )
        exit(-1)


def setup_logging(
    logging_config: LoggingConfig,
    engine_config: Union[Path, str] = "engine.prototxt"
) -> None:
    """Set up the logging for the current experiment.
    """
    time_stamp = datetime.datetime.now().strftime(
        "%Y-%m-%d-%H-%M-%S"
    )
    config.LOG_DIR = config.LOG_DIR.joinpath(
        f"{time_stamp}_{logging_config.log_dir}"
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sink=config.LOG_DIR.joinpath('console.log'),
        level=logging_config.level
    )

    if logging_config.verbose:
        logger.add(sink=sys.stderr, level=logging_config.level)
        logger.info(f"Logging to {config.LOG_DIR} ...")

    if isinstance(engine_config, str):
        engine_config = Path(engine_config).absolute()

    shutil.copy(engine_config, config.LOG_DIR.joinpath(f'{engine_config.name}'))
