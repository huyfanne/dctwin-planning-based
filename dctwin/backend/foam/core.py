import math
import shutil
from pathlib import Path
from typing import List, Optional, Union

from dctwin.backend import template_dir, template_env
from dctwin.config import environ
from dctwin.models.basics import Vertex


def generate_control_dict(
    probes: Optional[List[Vertex]] = None,
    steady=True,
    delta_t: Union[int, float] = 1,
    write_interval: int = 100,
    end_time: int = 500,
    process_num: int = 1,
) -> None:
    if steady is False:
        delta_t = float("1e-5")
    if probes is None:
        probes = list()

    system_folder = "steady"
    if steady is False:
        system_folder = "transient"
    shutil.copy(
        Path(template_dir, f"system/{system_folder}/fvSchemes"),
        Path(environ.CASE_DIR, "system/fvSchemes"),
    )
    shutil.copy(
        Path(template_dir, f"system/{system_folder}/fvSolution"),
        Path(environ.CASE_DIR, "system/fvSolution"),
    )
    with open(Path(environ.CASE_DIR, "system/controlDict"), "w") as f:
        f.write(
            template_env.get_template(f"system/{system_folder}/controlDict.j2").render(
                delta_t=delta_t,
                write_interval=write_interval,
                end_time=end_time,
                probes=probes,
            )
        )
    if process_num > 1:
        process_num = 2 ** round(math.log(process_num, 2))
        if process_num >= 64:
            process_num = 64
        with open(Path(environ.CASE_DIR, "system/decomposeParDict"), "w") as f:
            f.write(
                template_env.get_template("system/decomposeParDict.j2").render(
                    process_num=process_num
                )
            )


def init_foam():
    Path(environ.CASE_DIR, "0").mkdir(parents=True, exist_ok=True)
    Path(environ.CASE_DIR, "constant/triSurface").mkdir(parents=True, exist_ok=True)
    Path(environ.CASE_DIR, "system").mkdir(parents=True, exist_ok=True)
    Path(environ.CASE_DIR, "case.foam").touch(exist_ok=True)

    shutil.copy(Path(template_dir, "constant/g"), Path(environ.CASE_DIR, "constant/g"))
    shutil.copy(
        Path(template_dir, "constant/thermophysicalProperties"),
        Path(environ.CASE_DIR, "constant/thermophysicalProperties"),
    )
    shutil.copy(
        Path(template_dir, "constant/transportProperties"),
        Path(environ.CASE_DIR, "constant/transportProperties"),
    )

    with open(Path(environ.CASE_DIR, "constant/turbulenceProperties"), "w") as f:
        f.write(
            template_env.get_template("constant/turbulenceProperties.j2").render(
                turbulence=("on" if environ.SOLVER_TURBULENCE else "off")
            )
        )

    shutil.copy(
        Path(template_dir, "system/steady/fvSchemes"),
        Path(environ.CASE_DIR, "system/fvSchemes"),
    )
    shutil.copy(
        Path(template_dir, "system/steady/fvSolution"),
        Path(environ.CASE_DIR, "system/fvSolution"),
    )
    generate_control_dict()
