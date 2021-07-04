"""
form.k.value = 1.5 * Math.pow(form.Tu.value/100,2) * Math.pow(form.u_freestream.value,2)
form.epsilon.value = 0.09 * Math.pow(form.k.value,1.5) / form.Tu_L.value
form.omega.value = form.epsilon.value / (0.09 * form.k.value)
"""
import shutil
import subprocess
from decimal import Decimal
from logging import Logger
from pathlib import Path
from typing import List, Union

from dctwin.backend import template_env
from dctwin.backend.core import Backend
from dctwin.backend.foam.core import generate_control_dict
from dctwin.config import environ
from dctwin.models import ACU, Server
from dctwin.models.constructions import Room

logger = Logger(__file__)


class Builder:
    def __init__(self, room: Room):
        self.room_dz = room.height
        self.acu_list = list(room.objects.acus.values())
        self.server_list = list(room.objects.servers.values())

    def run(self):
        self.render('alphat')
        self.render('epsilon')
        self.render('nut')
        self.render('k')
        self.render('p')
        self.render('p_rgh')
        self.render('T')
        self.render('U')

    @classmethod
    def get_k_and_epsilon(cls, obj_list: List[Union[ACU, Server]]):
        """Get the minimum value greater than 0"""
        _obj_list = [acu for acu in obj_list if acu.k != 0]
        if len(_obj_list) == 0:
            raise ValueError('Please check the ACU flow rate value')
        obj = min(_obj_list, key=lambda x: x.k)
        return obj.k, obj.epsilon

    def render(self, filename):
        acu_k, acu_epsilon = self.get_k_and_epsilon(self.acu_list)
        server_k, server_epsilon = self.get_k_and_epsilon(self.server_list)
        with open(Path(environ.CASE_DIR, f'0/{filename}'), 'w') as f:
            f.write(
                template_env.get_template(f'0/{filename}.j2').render(
                    init_temperature=24 + 273.15,
                    p_rgh=self.room_dz * Decimal('9.81'),
                    acu_list=self.acu_list,
                    server_list=self.server_list,
                    acu_k=acu_k,
                    acu_epsilon=acu_epsilon,
                    server_k=server_k,
                    server_epsilon=server_epsilon,
                )
            )


def parse_result(case: str):
    results = []
    # case/postProcessing/probes/0/T
    with open(f'{case}/postProcessing/probes/0/T') as f:
        for i in f:
            if i.startswith('#'):
                continue
            else:
                results.append(
                    list(map(lambda x: round(float(x) - 273.15, 2), i.split()[1:]))
                )
    return results[-1]


def run(
    room: Room,
    steady=True,
    output: str = None,
    delta_t: int = 1,
    write_interval: int = 100,
    end_time: int = 500,
    process_num: int = 1,
    dry_run: bool = False,
):
    if steady:
        solver = 'buoyantBoussinesqSimpleFoam'
    else:
        solver = 'buoyantBoussinesqPimpleFoam'

    if output is not None:
        environ.CASE_DIR = Path(output).absolute()
        logger.info(f'Copying data to {environ.CASE_DIR}')

        shutil.copytree('case/0', f'{output}/0')
        shutil.copytree('case/constant', f'{output}/constant')
        shutil.copytree('case/system', f'{output}/system')
        Path(environ.CASE_DIR, 'case.foam').touch(exist_ok=True)

    generate_control_dict(
        room.probes,
        steady=steady,
        delta_t=delta_t,
        write_interval=write_interval,
        end_time=end_time,
        process_num=process_num,
    )
    builder = Builder(room)
    builder.run()
    logger.info(f'Generate boundary in {environ.CASE_DIR}')

    if process_num > 1:
        command = [
            'docker',
            'run',
            '--rm',
            '-v',
            f'{environ.CASE_DIR}:/data',
            '-w',
            '/data',
            'openfoamplus/of_v1912_centos73',
            'bash',
            '-c',
            '"source /opt/OpenFOAM/setImage_v1912.sh '
            '&& decomposePar -force '
            f'&& mpirun -np {process_num} --allow-run-as-root {solver} -parallel"',
        ]
    else:
        command = [
            'docker',
            'run',
            '--rm',
            '-v',
            f'{environ.CASE_DIR}:/data',
            '-w',
            '/data',
            'openfoamplus/of_v1912_centos73',
            'bash',
            '-c',
            'source /opt/OpenFOAM/setImage_v1912.sh',
            '&&',
            'echo',
            '&&',
            solver,
        ]
    if dry_run is False:
        subprocess.run(command)
    else:
        return command


class SteadySolverBackend(Backend):
    docker_image = 'openfoamplus/of_v1912_centos73'
    solver = 'buoyantBoussinesqSimpleFoam'

    @property
    def command(self):
        if self.process_num > 1:
            command = f"""
                bash -c 'source /opt/OpenFOAM/setImage_v1912.sh &&
                decomposePar -force && mpirun -np {self.process_num}
                --allow-run-as-root {self.solver} -parallel',
            """
        else:
            command = f"""
              bash -c 'source /opt/OpenFOAM/setImage_v1912.sh &&
              {self.solver}'
            """
        return command

    def run(self, room: Room):
        generate_control_dict(
            room.probes,
            steady=True,
            delta_t=1,
            write_interval=100,
            end_time=500,
            process_num=self.process_num,
        )
        builder = Builder(room)
        builder.run()

        if self.dry_run:
            return
        self.run_container()
