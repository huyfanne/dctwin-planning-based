import os
import shutil
import time
import socket
import datetime
import opyplus as op

from pathlib import Path
from typing import List, Tuple, Union
import xml.etree.ElementTree as ET

from docker import DockerClient
from loguru import logger
from dctwin.utils import EPlusEnvConfig
from dctwin.backends.eplus.utils import EPlusOutputFormatter
from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s
from dctwin.models import Eplus
from dctwin.utils import config


class EplusBackendMixin:
    """
    A class to handle the communication with the EnergyPlus with BCVTB
    :param proto_config: the configuration of the eplus model
    :param host: The host to connect to (default: "")
    :param network: The network to connect to (default: "")
    :param docker_client: The docker client to use (default: None)
    """

    docker_image = "ghcr.io/cap-dcwiz/energyplus-9-5-0:latest"
    _version = 2
    _cur_sim_time = 0.0
    _msg_buf_size = 2048
    _encoding = "ISO-8859-1"

    def __init__(
        self,
        proto_config: EPlusEnvConfig,
        docker_client: DockerClient = None,
        host: str = "",
        network: str = "",
        *args,
        **kwargs,
    ) -> None:
        super().__init__(client=docker_client, *args, **kwargs)
        self._host = host
        self._port = None
        self._socket = None
        self._network = network
        self._proto_config = proto_config
        self._set_up_socket()

    @staticmethod
    def _get_one_episode_len(idf_path: str) -> float:
        epm = op.Epm.load(idf_path)
        run_periods = epm.RunPeriod.one()
        begin_year = 2013
        begin_month = run_periods.begin_month
        begin_day_of_month = run_periods.begin_day_of_month
        end_year = 2013
        end_month = run_periods.end_month
        end_day_of_month = run_periods.end_day_of_month
        start_time = datetime.datetime(
            begin_year, begin_month, begin_day_of_month, 0, 0, 0
        )
        end_time = datetime.datetime(
            end_year, end_month, end_day_of_month, 23, 0, 0
        ) + datetime.timedelta(0, 3600)
        delta_sec = (end_time - start_time).total_seconds()
        return delta_sec

    def _set_up_socket(self) -> None:
        """Create a socket for communication with the BCVTB"""
        self._socket = socket.socket()
        # Enable keep-alive for the socket
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._socket.settimeout(3600)
        self._socket.bind(("0.0.0.0", 0))
        self._socket.listen()
        if self._host == "":
            self._host = socket.gethostbyname(socket.gethostname())
        self._port = self._socket.getsockname()[1]
        logger.info(f"socket listening on {self._host}:{self._port}")

    @staticmethod
    def _create_socket_cfg(host: str, port: int) -> None:
        """Create socket config file so that BCVTB can work with"""
        top = ET.Element("BCVTB-client")
        ipc = ET.SubElement(top, "ipc")
        _ = ET.SubElement(ipc, "socket", {"port": str(port), "hostname": host})
        tree = ET.ElementTree(top)
        ET.indent(tree, space="\t", level=0)
        with open(config.eplus.case_dir.joinpath("socket.cfg"), "wb") as f:
            f.write(
                '<?xml version="1.0" encoding="ISO-8859-1"?>\n'.encode("ISO-8859-1")
            )
            tree.write(f)

    def run(
        self, episode_idx: int = 0
    ) -> Tuple[Union[float, None], Union[float, None]]:
        self._pre_process(episode_idx)
        obs, done = self._run_backend()
        return obs, done

    @property
    def command(self) -> List[str]:
        assert isinstance(config.eplus.weather_file, Path)
        assert isinstance(config.eplus.idf_file, Path)
        return [
            f"/bin/bash",
            f"-c",
            f"/usr/local/EnergyPlus-9-5-0/energyplus "
            f"-w {config.eplus.weather_file.name} "
            f"-r {config.eplus.idf_file.name}",
        ]

    def _parse_idf_and_gen_bcvtb_config(
        self,
        idf_path: Union[str, Path],
    ) -> None:
        logger.info("Parsing IDF file...")
        self.idf_parser = Eplus.load(idf_path=str(idf_path))
        action_configs = self._proto_config.actions
        observation_configs = self._proto_config.observations
        self.idf_parser.batch_set_actions(action_configs)
        self.idf_parser.batch_set_observations(observation_configs)
        self.idf_parser.set_simulation_time(self._proto_config.simulation_time_config)
        self.idf_parser.set_external_interface()
        inlet_schedule_configs = self.idf_parser.batch_set_inlet_temperature_schedule(
            env_config=self._proto_config
        )
        ret_schedule_configs = self.idf_parser.batch_set_return_temperature_schedule(
            env_config=self._proto_config,
        )
        if inlet_schedule_configs is None and ret_schedule_configs is None:
            schedule_configs = None
        else:
            schedule_configs = inlet_schedule_configs + ret_schedule_configs
        self.idf_parser.save(save_path=str(idf_path))
        logger.info("Generating BCVTB Config ...")
        self.idf_parser.save_cfg_xml(
            observation_configs=self._proto_config.observations,
            action_configs=self._proto_config.actions,
            save_path=config.eplus.case_dir.joinpath("variables.cfg"),
            schedule_configs=schedule_configs,
        )

    def _pre_process(self, episode_idx: int = 0) -> None:
        # create case folder
        config.eplus.case_dir = Path(config.LOG_DIR).joinpath(
            f"eplus_output/episode-{episode_idx}"
        )
        Path(config.eplus.case_dir).mkdir(parents=True, exist_ok=True)
        # copy idf and weather files to the CASE folder
        if config.eplus.idf_file.exists() and config.eplus.weather_file.exists():
            weather_path = Path(config.eplus.case_dir).joinpath(
                config.eplus.weather_file.name
            )
            idf_path = Path(config.eplus.case_dir).joinpath(config.eplus.idf_file.name)
            shutil.copy(config.eplus.idf_file, idf_path)
            shutil.copy(config.eplus.weather_file, weather_path)
        else:
            raise FileNotFoundError(
                "Please check if the idf file and weather file exist"
            )
        self._parse_idf_and_gen_bcvtb_config(
            idf_path=str(idf_path),
        )
        self._end_sim_time = self._get_one_episode_len(str(idf_path))
        self._create_socket_cfg(self._host, self._port)

    @staticmethod
    def _post_process() -> None:
        """process the output of the energyplus simulation"""
        time.sleep(10)
        try:
            EPlusOutputFormatter.group_into_csv(str(config.eplus.case_dir))
        except FileNotFoundError:
            logger.info(f"Failed to clean output dir {config.eplus.case_dir}")

    def _run_backend(self) -> Tuple[Union[float, None], Union[float, None]]:
        host_path = os.environ.get("HOST_PATH", None)
        if host_path is not None:
            # concatenate the log path in Docker container with external host path
            log_index = config.eplus.case_dir.parts.index("log")
            case_dir = "/".join(config.eplus.case_dir.parts[log_index:])
            case_dir = Path(host_path).joinpath(case_dir)
            logger.info(f"Concatenated Case Directory: {case_dir}")
            network = None
            network_mode = f"container:{socket.gethostname()}"
        else:
            case_dir = config.eplus.case_dir
            network = self._network
            network_mode = None
        self.run_container(
            environment={
                "BCVTB_HOME": "/usr/local/bcvtb",
            },
            background=True,
            case_dir=case_dir,
            network=network,
            network_mode=network_mode,
        )
        while True:
            try:
                self._conn, addr = self._socket.accept()
                logger.info(f"Got connection from {addr}")
                break
            except socket.timeout:
                logger.info("Waiting for connection...")
                break
        return self.receive_status()  # as it cannot be done on the very first step

    def _serialize(self, actions: list) -> str:
        """Serialize actions into formatted string"""
        flag = 0 if len(actions) else 1
        meta_info = [
            str(self._version),
            str(flag),
            str(len(actions)),
            "0",
            "0",
            "{:20.15e}".format(self._cur_sim_time),
        ]
        action_str = []
        for action in actions:
            action_str.append("{:20.15e}".format(action))
        ret = " ".join(meta_info + action_str)
        ret += "\n"
        return ret

    def _deserialize(self, msg: str) -> Tuple[List[float], bool]:
        """Deserialize received message from Eplus into list of raw observations"""
        msg = msg.split(" ")
        self._version = int(msg[0])
        if int(msg[1]) == 1:  # no more obs, end
            return [], True
        try:
            self._cur_sim_time = float(msg[5])
        except IndexError:
            logger.critical(f"Error Message: {msg}")
            exit(-1)
        observations = []
        for i in range(6, len(msg)):
            observations.append(float(msg[i]))
        return observations, False

    def send_action(self, action) -> None:
        """
        Send actions to Eplus
        """
        msg = self._serialize(action)
        self._conn.send(msg.encode())

    # def _get_parsed_msg(self) -> Tuple[List[float], bool]:
    #     return self._deserialize(
    #         self._conn.recv(self._msg_buf_size).decode(encoding=self._encoding).strip()
    #     )

    def _get_parsed_msg(self) -> Tuple[List[float], bool]:
        # Initialize an empty buffer to store the received data
        buffer = bytearray()

        # Loop until the entire message is received
        while True:
            chunk = self._conn.recv(self._msg_buf_size)
            if not chunk:
                raise Exception("Connection closed by the other end")
            buffer.extend(chunk)
            # print('buffer:', buffer)
            if self._termination_condition_met(buffer):
                return self._deserialize(buffer.decode(encoding=self._encoding).strip())

    def _termination_condition_met(self, buffer: bytearray) -> bool:
        return b"\n" in buffer  # Change '\n' to your desired termination condition

    def receive_status(self) -> Tuple[Union[List[float], None], bool]:
        """
        Receive observations from Eplus
        """
        obs, terminated = self._get_parsed_msg()
        if terminated:
            logger.critical(
                "Eplus terminated unexpectedly. "
                "Likely to be the wrongly estimated simulation time. "
                "Please check env._curSimTim"
            )
            # disable for eureka deployment due to 1 time step simulation
            exit(0)
        if self._cur_sim_time >= self._end_sim_time:
            logger.debug("Came to the end of one episode, terminating")
            done = True
            self.close()
        else:
            done = False
        return obs, done

    def close(self) -> None:
        self.send_action([])
        self._post_process()

    def __del__(self) -> None:
        """Close Eplus process and socket connection"""
        if hasattr(self, "_socket") and self._socket is not None:
            logger.debug("Closing socket...")
            if hasattr(self, "_conn"):
                self._conn.close()
            self._socket.close()
        logger.debug("EnergyPlus backend closed")


class EplusBackend(EplusBackendMixin, Backend):
    pass


class EplusBackendK8s(EplusBackendMixin, BackendK8s):
    pass
