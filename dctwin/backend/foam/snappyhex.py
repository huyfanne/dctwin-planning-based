from dctwin.models.objects import Rack
import math
import os
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Optional

import click

from dctwin.backend import template_env
from dctwin.backend.core import Backend
from dctwin.backend.foam.core import init_foam
from dctwin.config import environ
from dctwin.models.basics import Vertex
from dctwin.models.constructions import Room

logger = Logger(__name__)


@dataclass
class Mesh:
    name: str
    level: int
    type: str
    refine_level: str
    face_type: Optional[str] = None


def generate_block_dict(room: Room):
    min_z = (
        0
        if room.constructions.raised_floor is None
        else -room.constructions.raised_floor.height
    )
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

    base_size = environ.base_size
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
    with open(Path(environ.CASE_DIR, "system/blockMeshDict"), "w") as f:
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
):
    files = os.listdir(Path(environ.geometry_dir))
    files.sort()
    files = list(filter(lambda x: ".stl" in x, files))
    new_field_config = {
        "room_wall": {"type": "wall", "level": 1, "refine_level": "(0 1)"},
        "partition_wall": {"type": "wall", "level": 1, "refine_level": "(0 1)"},
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
            name=mesh_name,
            level=mesh_category["level"],
            type=mesh_category["type"],
            refine_level=mesh_category["refine_level"],
        )
        if mesh_category.get("faceType"):
            mesh.face_type = mesh_category["faceType"]
            baffle_faces.append(mesh)
        mesh_list.append(mesh)

    assert len(mesh_list) == len(files)
    with open(Path(environ.CASE_DIR, "system/surfaceFeatureExtractDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/surfaceFeatureExtractDict.j2").render(
                files=files
            )
        )

    # location = Vertex(x=(room.plane_outline[0].x + room.plane_outline[2].y)/2,
    #                   y=(room.plane_outline[0].y + room.plane_outline[2].y)/2,
    #                   z=room.height - 0.01)
    first_rack: Rack = list(room.objects.racks.values())[0]
    location = Vertex(
        x=first_rack.placement.x,
        y=first_rack.placement.y,
        z=(room.height + first_rack.size.dz) / 2,
    )
    with open(Path(environ.CASE_DIR, "system/snappyHexMeshDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/snappyHexMeshDict.j2").render(
                mesh_list=mesh_list, location=location
            )
        )
    with open(Path(environ.CASE_DIR, "system/createPatchDict"), "w") as f:
        f.write(
            template_env.get_template("mesh/createPatchDict.j2").render(
                baffle_faces=baffle_faces
            )
        )
    if process_num > 1:
        if process_num >= 16:
            process_num = 16
        elif process_num >= 8:
            process_num = 8
        elif process_num >= 4:
            process_num = 4
        elif process_num >= 2:
            process_num = 2
        with open(Path(environ.CASE_DIR, "system/decomposeParDict"), "w") as f:
            f.write(
                template_env.get_template("system/decomposeParDict.j2").render(
                    process_num=process_num
                )
            )


class SnappyHexBackend(Backend):
    docker_image = "openfoamplus/of_v1912_centos73"

    @property
    def command(self):
        if self.process_num > 1:
            command = (
                "bash -c 'source /opt/OpenFOAM/setImage_v1912.sh && "
                "blockMesh && surfaceFeatureExtract && "
                "decomposePar -copyZero -force && "
                f"mpirun -np {self.process_num} snappyHexMesh -parallel -overwrite && "
                "reconstructParMesh -constant -mergeTol 6 && "
                "createPatch -overwrite && "
                "rm -rf /data/constant/triSurface/*.eMesh' && "
                "rm -rf /data/processor*"
            )
        else:
            command = (
                "bash -c 'source /opt/OpenFOAM/setImage_v1912.sh && "
                "blockMesh && surfaceFeatureExtract && snappyHexMesh -overwrite && "
                "createPatch -overwrite && rm -rf /data/constant/triSurface/*.eMesh'"
            )
        return command

    def run(
        self,
        room: Room,
        dry_run: bool = False,
        process_num: int = None,
        field_config: Optional[dict] = None,
    ):
        if process_num is not None:
            self.process_num = process_num

        init_foam()
        generate_block_dict(room)
        generate_snappy_dict(
            room, process_num=self.process_num, field_config=field_config
        )
        if dry_run:
            return
        self.run_container(user=os.getuid())
        click.echo("***** Mesh finished *****\n\n")
