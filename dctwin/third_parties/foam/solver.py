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

from dclib.room import Room

from dctwin.third_parties.docker_backend import DockerBackend
from dctwin.third_parties.k8s_backend import K8sBackend
from dctwin.third_parties.foam.boundary import ACUBoundary, RoomBoundary, ServerBoundary, HeatEmittingBoxBoundary

from dctwin.third_parties.foam.utils import generate_control_dict, read_internal_field
from dctwin.utils import template_env, config


class Builder:
    """
    A class to render the templates of the foam configuration file

    :param room: the room to be simulated
    :param last_state_case: the last state of the case, if it is None,
        the state will be reset to the initial state
    """

    def __init__(self, room: Room, last_state_case=None) -> None:
        self.room = room
        self.room_dz = room.geometry.height
        self.acu_dict = room.constructions.acus
        self.heat_emitting_box_dict = room.constructions.heat_emitting_boxes
        server_dict = {}
        for rack in room.constructions.racks.values():
            for server_key, server in rack.constructions.servers.items():
                server_dict[server_key] = server
        for row in room.constructions.rows.values():
            for rack in row.constructions.racks.values():
                for server_key, server in rack.constructions.servers.items():
                    server_dict[server_key] = server
        self.server_dict = server_dict
        self.last_state_case = last_state_case

    def run(self) -> None:
        self.render("alphat", "alphat")
        self.render("epsilon", "epsilon")
        self.render("nut", "nut")
        self.render("k", "k")
        self.render("p", "p")
        self.render("p_rgh", "p_rgh")

        if self.last_state_case is not None:
            self.render(
                "T", "T", "".join(read_internal_field(Path(self.last_state_case, "T")))
            )
            self.render(
                "U",
                "U",
                "".join(read_internal_field(Path(self.last_state_case, "U"))),
            )
        else:
            self.render("T", "T")
            self.render("U", "U")

    @classmethod
    def get_k_and_epsilon(cls, obj_dict: Dict) -> Tuple[float, float]:
        """Get the minimum value greater than 0"""
        _obj_list = [x for x in obj_dict.values() if x.k != 0]

        if len(_obj_list) == 0:
            raise ValueError("Please specify non-zero ACU, server, and heat-emitting boxes flow rates in model and inputs")

        obj = min(_obj_list, key=lambda x: x.k)
        return obj.k, obj.epsilon

    def render(self, source_filename, write_filename, internal_field=None) -> None:
        acu_k, acu_epsilon = self.get_k_and_epsilon(self.acu_dict)
        server_k, server_epsilon = self.get_k_and_epsilon(self.server_dict)
        
        try: 
            heat_emitting_box_k, heat_emitting_box_epsilon = self.get_k_and_epsilon(self.heat_emitting_box_dict)
        except: 
            heat_emitting_box_k, heat_emitting_box_epsilon = acu_k, acu_epsilon

        with open(Path(config.cfd.case_dir, f"0/{write_filename}"), "w") as f:
            f.write(
                template_env.get_template(f"foam/template/0/{source_filename}.j2").render(
                    init_temperature=24 + 273.15,
                    p_rgh=round(self.room_dz * 9.81, 10),
                    acu_boundaries=[
                        ACUBoundary(acu)
                        for acu in self.acu_dict.values()
                        ],
                    server_boundaries=[
                        ServerBoundary(server) 
                        for server in self.server_dict.values()
                        ],
                    heat_emitting_box_boundaries=[
                        HeatEmittingBoxBoundary(heat_emitting_box)
                        for heat_emitting_box in self.heat_emitting_box_dict.values()
                        ],
                    room_boundary=RoomBoundary(self.room),
                    acu_k=acu_k,
                    acu_epsilon=acu_epsilon,
                    server_k=server_k,
                    server_epsilon=server_epsilon,
                    heat_emitting_box_k=heat_emitting_box_k,
                    heat_emitting_box_epsilon=heat_emitting_box_epsilon,
                    internal_field=internal_field,
                )
            )


class SolverBackendMixin:
    """
    Backend for OpenFOAM solver. The class is inherited from the core Backend
    """

    _docker_image = "ghcr.io/cap-dcwiz/openfoam-2312-cuda-smi75:1.0.0"

    @property
    def docker_image(self) -> str:
        return self._docker_image

    @docker_image.setter
    def docker_image(self, value: str) -> None:
        self._docker_image = value

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
                    "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && "
                    "export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/amgx/lib && "
                    "decomposePar -force && "
                    "mpirun --use-hwthread-cpus --allow-run-as-root "
                    f"-np {self.process_num} {self.solver} -parallel && "
                    f"reconstructPar {latest_time} && "
                    "rm -rf /data/processor* && "
                    "postProcess -func 'writeCellCentres' -time 0 && "
                    "postProcess -func 'writeCellVolumes' -time 0"
                ),
            ]
        else:
            command = [
                "bash",
                "-c",
                (
                    f"source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && "
                    f"export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/amgx/lib && "
                    f"{self.solver} && "
                    "postProcess -func 'writeCellCentres' -time 0 && "
                    "postProcess -func 'writeCellVolumes' -time 0"
                ),
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

        room.dump(config.cfd.case_dir / "base_mesh_aligned_model.json")

        if write_interval is not None:
            self.write_interval = write_interval
        if end_time is not None:
            self.end_time = end_time
        self.generate_control_dict(room)

        if config.cfd.dry_run:
            return

        builder = Builder(room, last_state_case)
        builder.run()

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


class SolverDockerBackend(SolverBackendMixin, DockerBackend):
    pass


class SolverK8SBackend(SolverBackendMixin, K8sBackend):
    pass


class SteadySolverDockerBackend(SolverDockerBackend):
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
            is_gpu=self.is_gpu,
        )


class TransientSolverDockerBackend(SolverDockerBackend):
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
            is_gpu=self.is_gpu,
        )


class SteadySolverK8sBackend(SolverK8SBackend):
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
            is_gpu=self.is_gpu,
        )


class TransientSolverK8sBackend(SolverK8SBackend):
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
            is_gpu=self.is_gpu,
        )
