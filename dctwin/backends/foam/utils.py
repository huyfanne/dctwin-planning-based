import os
import math
import shutil
from typing import List
from dataclasses import dataclass

from dctwin.models.objects import Rack
from dctwin.utils import (
    template_env,
    template_dir,
    config,
)
from dctwin.models.basics import Vertex
from dctwin.models.constructions import Room

from pathlib import Path
from typing import Optional, Union


@dataclass
class Mesh:
    name: str
    level: int
    type: str
    refine_level: str
    face_type: Optional[str] = None


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
        Path(config.CASE_DIR, "system/fvSchemes"),
    )
    shutil.copy(
        Path(template_dir, f"system/{system_folder}/fvSolution"),
        Path(config.CASE_DIR, "system/fvSolution"),
    )
    with open(Path(config.CASE_DIR, "system/controlDict"), "w") as f:
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
        with open(Path(config.CASE_DIR, "system/decomposeParDict"), "w") as f:
            f.write(
                template_env.get_template("system/decomposeParDict.j2").render(
                    process_num=process_num
                )
            )


def init_foam():
    Path(config.CASE_DIR, "0").mkdir(parents=True, exist_ok=True)
    Path(config.CASE_DIR, "constant/triSurface").mkdir(parents=True, exist_ok=True)
    Path(config.CASE_DIR, "system").mkdir(parents=True, exist_ok=True)
    Path(config.CASE_DIR, "case.foam").touch(exist_ok=True)

    shutil.copy(Path(template_dir, "constant/g"), Path(config.CASE_DIR, "constant/g"))
    shutil.copy(
        Path(template_dir, "constant/thermophysicalProperties"),
        Path(config.CASE_DIR, "constant/thermophysicalProperties"),
    )
    shutil.copy(
        Path(template_dir, "constant/transportProperties"),
        Path(config.CASE_DIR, "constant/transportProperties"),
    )

    with open(Path(config.CASE_DIR, "constant/turbulenceProperties"), "w") as f:
        f.write(
            template_env.get_template("constant/turbulenceProperties.j2").render(
                turbulence=("on" if config.SOLVER_TURBULENCE else "off")
            )
        )

    shutil.copy(
        Path(template_dir, "system/steady/fvSchemes"),
        Path(config.CASE_DIR, "system/fvSchemes"),
    )
    shutil.copy(
        Path(template_dir, "system/steady/fvSolution"),
        Path(config.CASE_DIR, "system/fvSolution"),
    )
    generate_control_dict()


def generate_block_dict(room: Room) -> None:
    """Generate the blockMeshDict file"""
    min_z = 0
    v_min, v_max = Vertex(x=0, y=0, z=min_z), Vertex(x=0, y=0, z=room.height)
    for vertex in room.plane_outline:
        if vertex.x < v_min.x:
            v_min.x = vertex.x
        if vertex.y < v_min.y:
            v_min.y = vertex.y
        if vertex.x > v_max.x:
            v_max.x = vertex.x
        if vertex.y > v_max.y:
            v_max.y = vertex.y

    base_size = config.base_size
    x_cells = math.ceil((v_max.x - v_min.x) / base_size)
    if base_size * x_cells != (v_max.x - v_min.x):
        v_max.x = x_cells * base_size - v_min.x
    y_cells = math.ceil((v_max.y - v_min.y) / base_size)
    if base_size * y_cells != (v_max.y - v_min.y):
        v_max.y = y_cells * base_size - v_min.y
    z_cells = math.ceil((v_max.z - v_min.z) / base_size)
    if base_size * z_cells != (v_max.z - v_min.z):
        v_max.z = z_cells * base_size - v_min.z

    v_min.x -= 0.1
    v_min.y -= 0.1
    v_min.z -= 0.1
    v_max.x += 0.1
    v_max.y += 0.1
    v_max.z += 0.1

    template = template_env.get_template("mesh/blockMeshDict.j2")
    with open(Path(config.CASE_DIR, "system/blockMeshDict"), "w") as f:
        f.write(
            template.render(
                v_max=v_max,
                v_min=v_min,
                x_cells=x_cells,
                y_cells=y_cells,
                z_cells=z_cells,
            )
        )


def generate_snappy_dict(
    room: Room, field_config: Optional[dict] = None, process_num: int = 1
) -> None:
    """Generate the snappyHexMeshDict file"""
    files = os.listdir(Path(config.geometry_dir))
    files.sort()
    files = list(filter(lambda x: ".stl" in x, files))
    new_field_config = {
        "room_wall": {"type": "wall", "level": 1, "refine_level": "(0 1)"},
        "partition_wall": {"type": "wall", "level": 1, "refine_level": "(0 1)"},
        "pillar": {"type": "wall", "level": 1, "refine_level": "(0 1)"},
        "acu_wall": {"type": "wall", "level": 2, "refine_level": "(0 2)"},
        "acu_return": {"type": "patch", "level": 2, "refine_level": "(0 2)"},
        "acu_supply": {"type": "patch", "level": 2, "refine_level": "(0 2)"},
        "server_inlet": {"type": "patch", "level": 2, "refine_level": "(0 3)"},
        "server_outlet": {"type": "patch", "level": 2, "refine_level": "(0 3)"},
        "server_wall": {"type": "wall", "level": 2, "refine_level": "(0 3)"},
        "rack_wall": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
        "rack_panel": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
        "ceiling": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
        "duct": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
        "containment": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
        "floor": {
            "type": "wall",
            "level": 2,
            "refine_level": "(0 2)",
            "faceType": "baffle",
        },
    }
    if field_config:
        new_field_config = {**new_field_config, **field_config}
    mesh_list = []
    baffle_faces = []
    for filename in files:
        mesh_name = filename.split(".")[0]
        mesh_category = None
        for k, v in new_field_config.items():
            if mesh_name.startswith(k):
                mesh_category = v
                break
        if mesh_category is None:
            raise ValueError("No field config for snappyHex")
        mesh = Mesh(
            name=str(mesh_name),
            level=mesh_category["level"],
            type=mesh_category["type"],
            refine_level=mesh_category["refine_level"],
        )
        if mesh_category.get("faceType"):
            mesh.face_type = mesh_category["faceType"]
            baffle_faces.append(mesh)
        mesh_list.append(mesh)

    assert len(mesh_list) == len(files)
    with open(Path(config.CASE_DIR, "system/surfaceFeatureExtractDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/surfaceFeatureExtractDict.j2").render(
                files=files
            )
        )

    first_rack: Rack = list(room.objects.racks.values())[0]
    location = Vertex(
        x=first_rack.placement.x,
        y=first_rack.placement.y,
        z=(room.height + first_rack.size.dz) / 2,
    )
    with open(Path(config.CASE_DIR, "system/snappyHexMeshDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/snappyHexMeshDict.j2").render(
                mesh_list=mesh_list, location=location
            )
        )
    with open(Path(config.CASE_DIR, "system/createPatchDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/createPatchDict.j2").render(
                baffle_faces=baffle_faces
            )
        )
    if process_num > 1:
        process_num = 2 ** int(math.log(process_num, 2))
        with open(Path(config.CASE_DIR, "system/decomposeParDict"), "w") as f:
            f.write(
                template_env.get_template("system/decomposeParDict.j2").render(
                    process_num=process_num
                )
            )


def read_internal_field(filename: Union[str, Path]):
    with open(filename) as f:
        started = False
        for line in f:
            if line.strip().startswith("internalField"):
                started = True
                yield line[len("internalField"):]
            elif started:
                if ";" not in line:
                    yield line
                else:
                    return
            else:
                continue
