"""
form.k.value = 1.5 * Math.pow(form.Tu.value/100,2) * Math.pow(form.u_freestream.value,2)
form.epsilon.value = 0.09 * Math.pow(form.k.value,1.5) / form.Tu_L.value
form.omega.value = form.epsilon.value / (0.09 * form.k.value)
"""
import abc
import os
import shutil
import time
from pathlib import Path
from typing import Tuple, Dict

from loguru import logger

from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s
from dctwin.backends.foam.boundary import ACUBoundary, RoomBoundary, ServerBoundary

from dctwin.backends.foam.utils import generate_control_dict, read_internal_field
from dctwin.models import Room
from dctwin.utils import template_env, config


class Builder:
    """
    A class to render the template of the foam configuration file

    :param room: the room to be simulated
    :param last_state_case: the last state of the case, if it is None,
        the state will be reset to the initial state
    """

    def __init__(self, room: Room, last_state_case=None) -> None:
        self.room = room
        self.room_dz = room.geometry.height
        self.acu_dict = room.constructions.acus
        server_dict = {}
        for rack in room.constructions.racks.values():
            for server_key, server in rack.constructions.servers.items():
                server_dict[server_key] = server
        self.server_dict = server_dict
        self.last_state_case = last_state_case

    def run(self) -> None:
        self.render("alphat")
        self.render("epsilon")
        self.render("nut")
        self.render("k")
        self.render("p")
        self.render("p_rgh")
        if self.last_state_case is not None:
            self.render(
                "T", "".join(read_internal_field(Path(self.last_state_case, "T")))
            )
            self.render(
                "U", "".join(read_internal_field(Path(self.last_state_case, "U")))
            )
        else:
            self.render("T")
            self.render("U")

    @classmethod
    def get_k_and_epsilon(cls, obj_dict: Dict) -> Tuple[float, float]:
        """Get the minimum value greater than 0"""
        _obj_list = [acu for acu in obj_dict.values() if acu.k != 0]
        if len(_obj_list) == 0:
            raise ValueError("Please check the ACU flow rate value")
        obj = min(_obj_list, key=lambda x: x.k)
        return obj.k, obj.epsilon

    def render(self, filename, internal_field=None) -> None:
        acu_k, acu_epsilon = self.get_k_and_epsilon(self.acu_dict)
        server_k, server_epsilon = self.get_k_and_epsilon(self.server_dict)
        with open(Path(config.cfd.case_dir, f"0/{filename}"), "w") as f:
            f.write(
                template_env.get_template(f"0/{filename}.j2").render(
                    init_temperature=24 + 273.15,
                    p_rgh=round(self.room_dz * 9.81, 10),
                    acu_boundaries=[
                        ACUBoundary(key, acu) for key, acu in self.acu_dict.items()
                    ],
                    server_boundaries=[
                        ServerBoundary(key, server)
                        for key, server in self.server_dict.items()
                    ],
                    room_boundary=RoomBoundary(self.room),
                    acu_k=acu_k,
                    acu_epsilon=acu_epsilon,
                    server_k=server_k,
                    server_epsilon=server_epsilon,
                    internal_field=internal_field,
                )
            )


class SolverBackendMixin:
    """
    Backend for OpenFOAM solver. The class is inherited from the core Backend
    """

    docker_image = "ghcr.io/cap-dcwiz/openfoam-v1912-centos72:latest"

    only_save_latest = True
    write_interval = 10
    end_time = 500

    @property
    @abc.abstractmethod
    def solver(self) -> str:
        raise NotImplementedError

    @property
    def command(self) -> str:
        if self.process_num > 1:
            latest_time = "-latestTime" if self.only_save_latest else ""
            command = [
                "bash",
                "-c",
                (
                    "source /opt/OpenFOAM/setImage_v1912.sh && "
                    "decomposePar -force && "
                    "mpirun --allow-run-as-root "
                    f"-np {self.process_num} {self.solver} -parallel && "
                    f"reconstructPar {latest_time} && "
                    "rm -rf /data/processor*"
                ),
            ]
        else:
            command = [
                "bash",
                "-c",
                (f"source /opt/OpenFOAM/setImage_v1912.sh && {self.solver}"),
            ]
        return command

    @classmethod
    def probe_result(cls) -> list:
        results = []
        with open(f"{config.cfd.case_dir}/postProcessing/probes/0/T") as f:
            for i in f:
                if i.startswith("#"):
                    continue
                else:
                    results.append(
                        list(map(lambda x: round(float(x) - 273.15, 2), i.split()[1:]))
                    )
        return results[-1]

    def generate_control_dict(self, room: Room) -> None:
        raise NotImplementedError

    def run(
        self,
        room: Room,
        last_state_case=None,
        process_num: int = None,
        write_interval: int = None,
        end_time: int = None,
        stream: bool = False,
    ) -> None:
        if process_num is not None:
            self.process_num = process_num

        if config.cfd.mesh_dir != Path("") and config.cfd.case_dir != Path(""):
            config.cfd.case_dir.mkdir(parents=True, exist_ok=True)
            config.cfd.case_dir = Path(config.cfd.case_dir).absolute()
            if not Path(f"{config.cfd.case_dir}/0").exists():
                shutil.copytree(f"{config.cfd.mesh_dir}/0", f"{config.cfd.case_dir}/0")
            if not Path(f"{config.cfd.case_dir}/constant").exists():
                shutil.copytree(
                    f"{config.cfd.mesh_dir}/constant", f"{config.cfd.case_dir}/constant"
                )
            if not Path(f"{config.cfd.case_dir}/system").exists():
                shutil.copytree(
                    f"{config.cfd.mesh_dir}/system", f"{config.cfd.case_dir}/system"
                )
            Path(config.cfd.case_dir, "case.foam").touch(exist_ok=True)
            time.sleep(1)

        if write_interval is not None:
            self.write_interval = write_interval
        if end_time is not None:
            self.end_time = end_time
        self.generate_control_dict(room)

        builder = Builder(room, last_state_case)
        builder.run()

        if config.cfd.dry_run:
            return

        host_path = os.environ.get("HOST_PATH", None)
        if host_path is not None:
            # concatenate the log path in Docker container with external host path
            log_index = config.cfd.case_dir.parts.index("log")
            case_dir = "/".join(config.cfd.case_dir.parts[log_index:])
            case_dir = Path(host_path).joinpath(case_dir)
            logger.info(f"Concatenated Case Directory: {case_dir}")
        else:
            case_dir = config.cfd.case_dir

        return self.run_container(user=0, stream=stream, case_dir=case_dir)


class SolverBackend(SolverBackendMixin, Backend):
    pass


class SolverBackendK8s(SolverBackendMixin, BackendK8s):
    pass


class SteadySolverBackend(SolverBackend):
    solver = "buoyantBoussinesqSimpleFoam"
    write_interval = 100
    end_time = 500

    def generate_control_dict(
        self,
        room: Room,
        delta_t=1,
    ) -> None:
        generate_control_dict(
            probes=list(
                [x.geometry.location for x in room.constructions.sensors.values()]
            ),
            steady=True,
            delta_t=delta_t,
            write_interval=self.write_interval,
            end_time=self.end_time,
            process_num=self.process_num,
        )


class TransientSolverBackend(SolverBackend):
    solver = "buoyantBoussinesqPimpleFoam"
    write_interval = 10
    end_time = 50

    def generate_control_dict(
        self,
        room: Room,
        delta_t=1e-5,
    ) -> None:
        generate_control_dict(
            probes=list(
                [x.geometry.location for x in room.constructions.sensors.values()]
            ),
            steady=False,
            delta_t=delta_t,
            write_interval=self.write_interval,
            end_time=self.end_time,
            process_num=self.process_num,
        )


class SteadySolverBackendK8s(SolverBackendK8s):
    solver = "buoyantBoussinesqSimpleFoam"
    write_interval = 100
    end_time = 500

    def generate_control_dict(
        self,
        room: Room,
        delta_t=1,
    ) -> None:
        generate_control_dict(
            probes=list(
                [x.geometry.location for x in room.constructions.sensors.values()]
            ),
            steady=True,
            delta_t=delta_t,
            write_interval=self.write_interval,
            end_time=self.end_time,
            process_num=self.process_num,
        )


class TransientSolverBackendK8s(SolverBackendK8s):
    solver = "buoyantBoussinesqPimpleFoam"
    write_interval = 10
    end_time = 50

    def generate_control_dict(
        self,
        room: Room,
        delta_t=1e-5,
    ) -> None:
        generate_control_dict(
            probes=list(
                [x.geometry.location for x in room.constructions.sensors.values()]
            ),
            steady=False,
            delta_t=delta_t,
            write_interval=self.write_interval,
            end_time=self.end_time,
            process_num=self.process_num,
        )
