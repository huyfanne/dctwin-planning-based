from typing import Dict, List
from pathlib import Path
from loguru import logger

from dclib import Room
from dclib.ite.servers.server import Server
from dclib.construction.surfaces import Panel
from dclib.cooling.room.facilities import ACU
from dclib.construction.entities import Box
from dclib.ite.racks import Rack
from dclib.models.geometry import Vertex
from dclib.room import Row

from dctwin.utils import template_env
from dctwin.third_parties.docker_backend import DockerBackend
from dctwin.third_parties.k8s_backend import K8sBackend

from .utils import is_closed, round_to_base, rotate_rectangular


class BoxModel:
    name: str
    v_min: list[float]
    v_max: list[float]
    is_refinement_box: False
    refinement_level: int = 0

    def __init__(
            self,
            name: str,
            v_min: List[float],
            v_max: List[float],
            is_refinement_box: False,
            refinement_level: int = 0
    ):
        self.name = name
        self.v_min = v_min
        self.v_max = v_max
        self.is_refinement_box = is_refinement_box
        self.refinement_level = refinement_level

    @property
    def snappyHex_cmd(self):
        searchable_box_cmd = f"""
        {self.name}
        {{
            type searchableBox;
            min ({self.v_min[0]} {self.v_min[1]} {self.v_min[2]});
            max ({self.v_max[0]} {self.v_max[1]} {self.v_max[2]});
        }}
        """
        refinement_surface_cmd = f"""
        {self.name}
        {{
            level (0 0);
            patchInfo {{
                type wall;
            }}
        }}
        """
        # if the box defines the region for refinement, add the refinement box command to densify the mesh inside the
        # region defined by the box
        if self.is_refinement_box:
            refinement_box_cmd = f"""
            {self.name}
            {{
                mode inside;
                levels ((0 {self.refinement_level}));
            }}
            """
        else:
            refinement_box_cmd = ""
        return searchable_box_cmd, refinement_surface_cmd, refinement_box_cmd


class PlaneModel:
    name: str
    origin: List[float]
    span: List[float]

    def __init__(
            self,
            name: str,
            origin: List[float],
            span: List[float],
    ):
        self.name = name
        self.origin = origin
        self.span = span

    @property
    def createBaffles_cmd(self):
        if "opening" in self.name:
            _createBaffles_cmd = f"""
                {self.name}
                {{
                    type        searchableSurface;
                    surface     searchablePlate;
                    origin      ({self.origin[0]} {self.origin[1]} {self.origin[2]});
                    span        ({self.span[0]} {self.span[1]} {self.span[2]});
                    patches
                    {{
                        master
                        {{
                            name            {self.name}_master_patches;
                            type            cyclic;
                            neighbourPatch  {self.name}_slave_patches;
                        }}
                        slave
                        {{
                            name            {self.name}_slave_patches;
                            type            cyclic;
                            neighbourPatch  {self.name}_master_patches;
                        }}
                    }}
                }}
                """
        else:
            _createBaffles_cmd = f"""
                {self.name}
                {{
                    type        searchableSurface;
                    surface     searchablePlate;
                    origin      ({self.origin[0]} {self.origin[1]} {self.origin[2]});
                    span        ({self.span[0]} {self.span[1]} {self.span[2]});
                    patches
                    {{
                        master
                        {{
                            name            {self.name}_master_patches;
                            type            wall;
                        }}
                        slave
                        {{
                            name            {self.name}_slave_patches;
                            type            wall;
                        }}
                    }}
                }}
                """

        return _createBaffles_cmd


class PatchModel:
    name: str
    bounding_box_min: List[float]
    bounding_box_max: List[float]
    face_set_name: str
    patch_name: str
    neighbour_patch_name: str

    def __init__(
            self,
            name: str,
            bounding_box_min: list,
            bounding_box_max: list,
            neighbour_patch_name: str = None
    ):
        self.name = name
        self.bounding_box_min = bounding_box_min
        self.bounding_box_max = bounding_box_max
        self.face_set_name = f"{name}_patches"
        self.patch_name = f"{name}"
        self.neighbour_patch_name = neighbour_patch_name if neighbour_patch_name else None

    @property
    def topoSet_cmd(self):
        if "rack_cyclic" in self.name:
            top_set_cmd = f"""
                {{
                    name    {self.face_set_name};
                    type    faceSet;
                    action  new;
                    source  boxToFace;
                    sourceInfo
                    {{
                        box  ({self.bounding_box_min[0]} {self.bounding_box_min[1]} {self.bounding_box_min[2]}) ({self.bounding_box_max[0]} {self.bounding_box_max[1]} {self.bounding_box_max[2]});
                    }}
                }}
                {{
                    name {self.face_set_name};
                    type faceSet;
                    action subset;
                    source boundaryToFace;
                    sourceInfo
                    {{
                    }}
                }}
                """
        else:
            top_set_cmd = f"""
                {{
                    name    {self.face_set_name};
                    type    faceSet;
                    action  new;
                    source  boxToFace;
                    sourceInfo
                    {{
                        box  ({self.bounding_box_min[0]} {self.bounding_box_min[1]} {self.bounding_box_min[2]}) ({self.bounding_box_max[0]} {self.bounding_box_max[1]} {self.bounding_box_max[2]});
                    }}
                }}
                {{
                    name {self.face_set_name};
                    type faceSet;
                    action subset;
                    source boundaryToFace;
                    sourceInfo
                    {{
                    }}
                }}
                """
        return top_set_cmd

    @property
    def createPatch_cmd(self):
        if "rack_cyclic" in self.name:
            create_patch_cmd = f"""
                {{
                    name {self.patch_name};
                    patchInfo
                    {{
                        type cyclic;
                        neighbourPatch {self.neighbour_patch_name};
                    }}
                    constructFrom set;
                    set {self.face_set_name};
                }}
                """
        else:
            create_patch_cmd = f"""
                {{
                    name {self.patch_name};
                    patchInfo
                    {{
                        type patch;
                    }}
                    constructFrom set;
                    set {self.face_set_name};
                }}
                """
        return create_patch_cmd


class ACUModel:
    config: ACU
    base_size: float
    box: BoxModel
    supply_face: PatchModel
    return_face: PatchModel

    def __init__(
            self,
            acu: ACU,
            base_size: float = 0.2
    ):
        self.config = acu
        self.base_size = base_size
        self.cheek_config()
        self._make_box()
        self._make_supply_face()
        self._make_return_face()

    def cheek_config(self):
        if not (self.config.geometry.orientation == 0 or self.config.geometry.orientation == 90 or
                self.config.geometry.orientation == 180 or self.config.geometry.orientation == 270):
            raise ValueError(f"Invalid orientation: {self.config.geometry.orientation} for ACU '{self.config.uid}'")

        if not (self.config.geometry.supply_face.side.name in ["top", "bottom", "left", "right", "front", "rear"]):
            raise ValueError(f"Invalid supply face side: {self.config.geometry.supply_face.side.name} for ACU '"
                             f"{self.config.uid}'")

        if not (self.config.geometry.return_face.side.name in ["top", "bottom", "left", "right", "front", "rear"]):
            raise ValueError(f"Invalid return face side: {self.config.geometry.return_face.side.name} for ACU '"
                             f"{self.config.uid}'")

    def _make_box(self):
        # compute the rotated vertex of the ACU object
        v_min, v_max = rotate_rectangular(
            abs_vertex_1=Vertex(
                x=self.config.geometry.location.x,
                y=self.config.geometry.location.y,
                z=self.config.geometry.location.z
            ),
            abs_vertex_2=Vertex(
                x=self.config.geometry.location.x + self.config.geometry.size.x,
                y=self.config.geometry.location.y,
                z=self.config.geometry.location.z
            ),
            abs_vertex_3=Vertex(
                x=self.config.geometry.location.x + self.config.geometry.size.x,
                y=self.config.geometry.location.y + self.config.geometry.size.y,
                z=self.config.geometry.location.z
            ),
            abs_vertex_4=Vertex(
                x=self.config.geometry.location.x,
                y=self.config.geometry.location.y + self.config.geometry.size.y,
                z=self.config.geometry.location.z
            ),
            angle=self.config.geometry.orientation,
        )
        v_min.z = self.config.geometry.location.z
        v_max.z = self.config.geometry.location.z + self.config.geometry.size.z
        # create a box object that represents the ACU
        self.box = BoxModel(
            name=f"acu_wall_{self.config.uid}",
            v_min=[v_min.x, v_min.y, v_min.z],
            v_max=[v_max.x, v_max.y, v_max.z],
            is_refinement_box=False
        )

    def _make_supply_face(self):
        acu_supply_face = self.config.geometry.supply_face
        bounding_box_min, bounding_box_max = self._get_supply_or_return_face_bounding_box(face=acu_supply_face)
        self.supply_face = PatchModel(
            name=f"acu_supply_{self.config.uid}",
            bounding_box_min=bounding_box_min,
            bounding_box_max=bounding_box_max
        )

    def _make_return_face(self):
        acu_return_face = self.config.geometry.return_face
        bounding_box_min, bounding_box_max = self._get_supply_or_return_face_bounding_box(face=acu_return_face)
        self.return_face = PatchModel(
            name=f"acu_return_{self.config.uid}",
            bounding_box_min=bounding_box_min,
            bounding_box_max=bounding_box_max
        )

    def _get_supply_or_return_face_bounding_box(self, face):
        orientation = int(self.config.geometry.orientation)
        if face.side.name == "bottom" or face.side.name == "top":
            bounding_box_min = [
                self.box.v_min[0] + face.offset.x
                if orientation in [0, 180] else self.box.v_min[0] + face.offset.y,

                self.box.v_min[1] + face.offset.y
                if orientation in [0, 180] else self.box.v_min[1] + face.offset.x,

                self.box.v_min[2] - 0.1 * self.base_size if face.side.name == "bottom"
                else self.box.v_min[2] + self.config.geometry.size.z - 0.1 * self.base_size
            ]
            bounding_box_max = [
                self.box.v_min[0] + face.offset.x + face.width
                if orientation in [0, 180] else self.box.v_min[0] + face.offset.y + face.length,

                self.box.v_min[1] + face.offset.y + face.length
                if orientation in [0, 180] else self.box.v_min[1] + face.offset.x + face.width,

                self.box.v_min[2] + 0.1 * self.base_size if face.side.name == "bottom"
                else self.box.v_min[2] + self.config.geometry.size.z + 0.1 * self.base_size
            ]
        elif face.side.name == "left" or face.side.name == "right":
            if self.config.geometry.orientation == 0 or self.config.geometry.orientation == 180:
                bounding_box_min = [
                    self.box.v_min[0] - 0.1 * self.base_size
                    if (face.side.name == "left" and self.config.geometry.orientation == 0) or
                       (face.side.name == "right" and self.config.geometry.orientation == 180)
                    else self.box.v_min[0] + self.config.geometry.size.x - 0.1 * self.base_size,
                    self.box.v_min[1] + face.offset.x,
                    self.box.v_min[2] + face.offset.y
                ]
                bounding_box_max = [
                    self.box.v_min[0] + 0.1 * self.base_size
                    if (face.side.name == "left" and self.config.geometry.orientation == 0) or
                       (face.side.name == "right" and self.config.geometry.orientation == 180)
                    else self.box.v_min[0] + self.config.geometry.size.x + 0.1 * self.base_size,
                    self.box.v_min[1] + face.offset.x + face.width,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
            else:
                bounding_box_min = [
                    self.box.v_min[0] + face.offset.x,
                    self.box.v_min[1] - 0.1 * self.base_size
                    if (face.side.name == "left" and self.config.geometry.orientation == 270) or
                       (face.side.name == "right" and self.config.geometry.orientation == 90)
                    else self.box.v_min[1] + self.config.geometry.size.y - 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y
                ]
                bounding_box_max = [
                    self.box.v_min[0] + face.offset.x + face.width,
                    self.box.v_min[1] + 0.1 * self.base_size
                    if (face.side.name == "left" and self.config.geometry.orientation == 270) or
                       (face.side.name == "right" and self.config.geometry.orientation == 90)
                    else self.box.v_min[1] + self.config.geometry.size.y + 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
        else:  # face.side.name == "front" or face.side.name == "rear":
            if self.config.geometry.orientation == 0 or self.config.geometry.orientation == 180:
                bounding_box_min = [
                    self.box.v_min[0] + face.offset.x,
                    self.box.v_min[1] - 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 0)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 180)
                    else self.box.v_min[1] + self.config.geometry.size.y - 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y
                ]
                bounding_box_max = [
                    self.box.v_min[0] + face.offset.x + face.width,
                    self.box.v_min[1] + 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 0)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 180)
                    else self.box.v_min[1] + self.config.geometry.size.y + 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
            else:
                bounding_box_min = [
                    self.box.v_min[0] + self.config.geometry.size.y - 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 90)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 270)
                    else self.box.v_min[0] - 0.1 * self.base_size,
                    self.box.v_min[1] + face.offset.x,
                    self.box.v_min[2] + face.offset.y
                ]
                bounding_box_max = [
                    self.box.v_min[0] + self.config.geometry.size.y + 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 90)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 270)
                    else self.box.v_min[0] + 0.1 * self.base_size,
                    self.box.v_min[1] + face.offset.x + face.width,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
        return bounding_box_min, bounding_box_max

    @property
    def snappyHex_cmd(self):
        return self.box.snappyHex_cmd

    @property
    def topoSet_cmd(self):
        return self.supply_face.topoSet_cmd + self.return_face.topoSet_cmd

    @property
    def createPatch_cmd(self):
        return self.supply_face.createPatch_cmd + self.return_face.createPatch_cmd


class ServerModel:
    config: Server
    v_min: Vertex
    v_max: Vertex
    slot_height: float
    base_size: float
    refine_size: float
    box: BoxModel
    inlet_face: PatchModel
    outlet_face: PatchModel

    def __init__(
            self,
            config: Server,
            v_min: Vertex,
            v_max: Vertex,
            slot_height: float = 0.05,
            base_size: float = 0.2,
            scale: int = 0
    ):
        self.config = config
        self.v_min = v_min
        self.v_max = v_max
        self.slot_height = slot_height
        self.base_size = base_size
        self.refine_size = base_size / (2 ** scale)
        self._make_inlet_outlet_face()

    def _get_bounding_box_min_max(self, x: int = None, y: int = None):
        orientation = int(self.config.geometry.orientation)
        if orientation == 0 or orientation == 180:
            bounding_box_min = [
                self.v_min.x,
                y - 0.1 * self.refine_size,
                self.v_min.z
            ]
            bounding_box_max = [
                round(self.v_min.x + (self.v_max.x - self.v_min.x) / 3, 3),
                y + 0.1 * self.refine_size,
                self.v_max.z
            ]
        elif orientation == 90 or orientation == 270:
            bounding_box_min = [
                x - 0.1 * self.refine_size,
                self.v_min.y,
                self.v_min.z
            ]
            bounding_box_max = [
                x + 0.1 * self.refine_size,
                round(self.v_min.y + (self.v_max.y - self.v_min.y) / 3, 3),
                self.v_max.z
            ]
        else:
            raise ValueError(f"Invalid orientation: {orientation} for server '{self.config.uid}'")

        return bounding_box_min, bounding_box_max

    def _make_inlet_outlet_face(self):
        orientation = int(self.config.geometry.orientation)
        if orientation in [0, 180]:
            y_inlet_face = self.v_min.y if orientation == 0 else self.v_max.y
            y_outlet_face = self.v_max.y if orientation == 0 else self.v_min.y
            x_inlet_face = None
            x_outlet_face = None
        else:  # orientation in [90, 270]
            y_inlet_face = None
            y_outlet_face = None
            x_inlet_face = self.v_max.x if orientation == 90 else self.v_min.x
            x_outlet_face = self.v_min.x if orientation == 90 else self.v_max.x

        bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(x=x_inlet_face, y=y_inlet_face)
        self.inlet_face = PatchModel(
            name=f"server_inlet_{self.config.uid}",
            neighbour_patch_name=f"server_outlet_{self.config.uid}",
            bounding_box_max=bounding_box_max,
            bounding_box_min=bounding_box_min
        )

        bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(x=x_outlet_face, y=y_outlet_face)
        self.outlet_face = PatchModel(
            name=f"server_outlet_{self.config.uid}",
            neighbour_patch_name=f"server_inlet_{self.config.uid}",
            bounding_box_max=bounding_box_max,
            bounding_box_min=bounding_box_min
        )

    @property
    def topoSet_cmd(self):
        return self.inlet_face.topoSet_cmd + self.outlet_face.topoSet_cmd

    @property
    def createPatch_cmd(self):
        return self.inlet_face.createPatch_cmd + self.outlet_face.createPatch_cmd


class RowRackModel:
    config: Row
    v_min: Vertex
    v_max: Vertex
    base_size: float
    refine_size: float
    refinement_level: int = 2
    box: BoxModel

    def __init__(
            self,
            row_rack: Row,
            base_size: float = 0.2,
            scale: int = 0,
            refinement_level: int = 2
    ):
        self.config = row_rack
        self.base_size = base_size
        self.refine_size = base_size / (2 ** scale)
        self.refine_region = None
        self.servers = []
        self.surrounding_planes = []
        self.blanking_panel = None
        self.slot_height = 0.05
        self.rack_cyclic_patch_list = []
        self.cheek_config()
        # compute the absolute coordinates of the rack object
        self.v_min, self.v_max = rotate_rectangular(
            abs_vertex_1=Vertex(
                x=row_rack.geometry.location.x,
                y=row_rack.geometry.location.y,
                z=row_rack.geometry.location.z
            ),
            abs_vertex_2=Vertex(
                x=row_rack.geometry.location.x + row_rack.geometry.size.x,
                y=row_rack.geometry.location.y,
                z=row_rack.geometry.location.z
            ),
            abs_vertex_3=Vertex(
                x=row_rack.geometry.location.x + row_rack.geometry.size.x,
                y=row_rack.geometry.location.y + row_rack.geometry.size.y,
                z=row_rack.geometry.location.z
            ),
            abs_vertex_4=Vertex(
                x=row_rack.geometry.location.x,
                y=row_rack.geometry.location.y + row_rack.geometry.size.y,
                z=row_rack.geometry.location.z
            ),
            angle=row_rack.geometry.orientation,
        )
        self.v_min.z = row_rack.geometry.location.z
        self.v_max.z = row_rack.geometry.location.z + row_rack.geometry.size.z
        # make the refinement level of the rack
        self.refinement_level = refinement_level
        # make the box of the rack
        self._make_box()
        # make the servers of the rack
        self._make_servers()
        # make the surrounding planes of the rack
        self.make_cyclic_patch()

    def cheek_config(self):
        RackModel.cheek_config(self)

    def _get_bounding_box_min_max(self, x: int = None, y: int = None, rack_v_max: Vertex = None,
                                  rack_v_min: Vertex = None, orientation: int = None):
        if orientation == 0 or orientation == 180:
            bounding_box_min = [
                round(rack_v_min.x + (rack_v_max.x - rack_v_min.x) * 2 / 3, 3),
                y - 0.1 * self.refine_size,
                rack_v_min.z
            ]
            bounding_box_max = [
                rack_v_max.x,
                y + 0.1 * self.refine_size,
                rack_v_max.z
            ]
        elif orientation == 90 or orientation == 270:
            bounding_box_min = [
                x - 0.1 * self.refine_size,
                round(rack_v_min.y + (rack_v_max.y - rack_v_min.y) * 2 / 3, 3),
                rack_v_min.z
            ]
            bounding_box_max = [
                x + 0.1 * self.refine_size,
                rack_v_max.y,
                rack_v_max.z
            ]
        else:
            raise ValueError(f"Invalid orientation: {orientation} for RowRack '{self.config.uid}'")

        return bounding_box_min, bounding_box_max

    def make_cyclic_patch(self):
        for rack in self.config.racks.values():
            # compute the absolute coordinates of the rack object
            rack_v_min, rack_v_max = rotate_rectangular(
                abs_vertex_1=Vertex(
                    x=rack.geometry.location.x,
                    y=rack.geometry.location.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_2=Vertex(
                    x=rack.geometry.location.x + rack.geometry.size.x,
                    y=rack.geometry.location.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_3=Vertex(
                    x=rack.geometry.location.x + rack.geometry.size.x,
                    y=rack.geometry.location.y + rack.geometry.size.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_4=Vertex(
                    x=rack.geometry.location.x,
                    y=rack.geometry.location.y + rack.geometry.size.y,
                    z=rack.geometry.location.z
                ),
                angle=rack.geometry.orientation,
            )
            rack_v_min.z = rack.geometry.location.z
            rack_v_max.z = rack.geometry.location.z + rack.geometry.size.z

            orientation = rack.geometry.orientation
            if orientation in [0, 180]:
                y_inlet_face = rack_v_min.y if orientation == 0 else rack_v_max.y
                y_outlet_face = rack_v_max.y if orientation == 0 else rack_v_min.y
                x_inlet_face = None
                x_outlet_face = None
            else:  # orientation in [90, 270]
                y_inlet_face = None
                y_outlet_face = None
                x_inlet_face = rack_v_max.x if orientation == 90 else rack_v_min.x
                x_outlet_face = rack_v_min.x if orientation == 90 else rack_v_max.x

            bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(
                x=x_inlet_face,
                y=y_inlet_face,
                rack_v_max=rack_v_max,
                rack_v_min=rack_v_min,
                orientation=orientation
            )
            self.rack_cyclic_patch_list.append(
                PatchModel(
                    name=f"rack_cyclic_{rack.uid}_master",
                    neighbour_patch_name=f"rack_cyclic_{rack.uid}_slave",
                    bounding_box_max=bounding_box_max,
                    bounding_box_min=bounding_box_min
                )
            )

            bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(
                x=x_outlet_face,
                y=y_outlet_face,
                rack_v_max=rack_v_max,
                rack_v_min=rack_v_min,
                orientation=orientation
            )
            self.rack_cyclic_patch_list.append(
                PatchModel(
                    name=f"rack_cyclic_{rack.uid}_slave",
                    neighbour_patch_name=f"rack_cyclic_{rack.uid}_master",
                    bounding_box_max=bounding_box_max,
                    bounding_box_min=bounding_box_min
                )
            )

    def _make_box(self):
        self.box = BoxModel(
            name=f'rack_wall_row_{self.config.uid}',
            v_min=[
                self.v_min.x,
                self.v_min.y,
                self.v_min.z,
            ],
            v_max=[
                self.v_max.x,
                self.v_max.y,
                self.v_max.z,
            ],
            is_refinement_box=True,
            refinement_level=self.refinement_level
        )

    def _make_servers(self):
        for rack in self.config.racks.values():
            rack_v_min, rack_v_max = rotate_rectangular(
                abs_vertex_1=Vertex(
                    x=rack.geometry.location.x,
                    y=rack.geometry.location.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_2=Vertex(
                    x=rack.geometry.location.x + rack.geometry.size.x,
                    y=rack.geometry.location.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_3=Vertex(
                    x=rack.geometry.location.x + rack.geometry.size.x,
                    y=rack.geometry.location.y + rack.geometry.size.y,
                    z=rack.geometry.location.z
                ),
                abs_vertex_4=Vertex(
                    x=rack.geometry.location.x,
                    y=rack.geometry.location.y + rack.geometry.size.y,
                    z=rack.geometry.location.z
                ),
                angle=rack.geometry.orientation,
            )
            rack_v_min.z = rack.geometry.location.z
            rack_v_max.z = rack.geometry.location.z + rack.geometry.size.z

            for server_name, server in rack.constructions.servers.items():
                if server.geometry.orientation != rack.geometry.orientation:
                    server.geometry.orientation = rack.geometry.orientation
                    logger.warning(f"Server '{server_name}' orientation is changed to {rack.geometry.orientation}, "
                                   f"because it is not the same as the rack orientation")
                orientation = server.geometry.orientation
                if orientation == 0 or orientation == 270:
                    server_v_min = Vertex(
                        x=rack_v_min.x,
                        y=rack_v_min.y,
                        z=rack_v_min.z + server.geometry.slot_position * self.slot_height
                    )
                    server_v_max = Vertex(
                        x=rack_v_min.x + server.geometry.width
                        if rack.geometry.orientation == 0 else rack_v_min.x + server.geometry.depth,

                        y=rack_v_min.y + server.geometry.depth
                        if rack.geometry.orientation == 0 else rack_v_min.y + server.geometry.width,

                        z=rack_v_min.z + (
                                    server.geometry.slot_position + server.geometry.slot_occupation) * self.slot_height
                    )
                else:  # orientation == 90 or orientation == 180:
                    server_v_min = Vertex(
                        x=rack_v_max.x - server.geometry.depth
                        if orientation == 90 else rack_v_min.x,

                        y=rack_v_min.y if orientation == 90 else rack_v_max.y - server.geometry.depth,
                        z=rack_v_min.z + server.geometry.slot_position * self.slot_height
                    )
                    server_v_max = Vertex(
                        x=rack_v_max.x,
                        y=rack_v_max.y,
                        z=rack_v_min.z + (
                                    server.geometry.slot_position + server.geometry.slot_occupation) * self.slot_height
                    )

                self.servers.append(
                    ServerModel(
                        config=server,
                        v_min=server_v_min,
                        v_max=server_v_max,
                        base_size=self.base_size,
                        slot_height=self.slot_height,
                    )
                )

    @property
    def snappyHex_cmd(self):
        return self.box.snappyHex_cmd

    @property
    def createBaffles_cmd(self):
        create_baffles_cmd = ""
        for plane in self.surrounding_planes:
            create_baffles_cmd += plane.createBaffles_cmd
        if self.blanking_panel:
            create_baffles_cmd += self.blanking_panel.createBaffles_cmd
        return create_baffles_cmd

    @property
    def topoSet_cmd(self):
        topo_set_cmd = ""
        for cyclic_patch in self.rack_cyclic_patch_list:
            topo_set_cmd += cyclic_patch.topoSet_cmd
        for server in self.servers:
            topo_set_cmd += server.topoSet_cmd
        return topo_set_cmd

    @property
    def createPatch_cmd(self):
        create_patch_cmd = ""
        for cyclic_patch in self.rack_cyclic_patch_list:
            create_patch_cmd += cyclic_patch.createPatch_cmd
        for server in self.servers:
            create_patch_cmd += server.createPatch_cmd
        return create_patch_cmd


class RackModel:
    config: Rack
    v_min: Vertex
    v_max: Vertex
    base_size: float
    refine_size: float
    refinement_level: int = 2
    box: BoxModel
    slot_height: float = 0.05

    def __init__(
            self,
            rack: Rack,
            base_size: float = 0.2,
            scale: int = 0,
            refinement_level: int = 2
    ):
        self.config = rack
        self.base_size = base_size
        self.refine_size = base_size / (2 ** scale)
        self.refine_region = None
        self.servers = []
        self.surrounding_planes = []
        self.blanking_panel = None
        self.slot_height = 0.05
        self.rack_cyclic_patch_list = []
        self.cheek_config()
        # compute the absolute coordinates of the rack object
        self.v_min, self.v_max = rotate_rectangular(
            abs_vertex_1=Vertex(
                x=rack.geometry.location.x,
                y=rack.geometry.location.y,
                z=rack.geometry.location.z
            ),
            abs_vertex_2=Vertex(
                x=rack.geometry.location.x + rack.geometry.size.x,
                y=rack.geometry.location.y,
                z=rack.geometry.location.z
            ),
            abs_vertex_3=Vertex(
                x=rack.geometry.location.x + rack.geometry.size.x,
                y=rack.geometry.location.y + rack.geometry.size.y,
                z=rack.geometry.location.z
            ),
            abs_vertex_4=Vertex(
                x=rack.geometry.location.x,
                y=rack.geometry.location.y + rack.geometry.size.y,
                z=rack.geometry.location.z
            ),
            angle=rack.geometry.orientation,
        )
        self.v_min.z = rack.geometry.location.z
        self.v_max.z = rack.geometry.location.z + rack.geometry.size.z
        # make the servers of the rack
        self._make_servers()
        # make the refinement region of the rack
        self.refinement_level = refinement_level
        # self._make_refinement_region()
        self._make_box()
        self.make_cyclic_patch()

    def _make_box(self):
        self.box = BoxModel(
            name=f'rack_wall_{self.config.uid}',
            v_min=[
                self.v_min.x,
                self.v_min.y,
                self.v_min.z,
            ],
            v_max=[
                self.v_max.x,
                self.v_max.y,
                self.v_max.z,
            ],
            is_refinement_box=True,
            refinement_level=self.refinement_level
        )

    def _get_bounding_box_min_max(self, x: int = None, y: int = None):
        orientation = int(self.config.geometry.orientation)
        if orientation == 0 or orientation == 180:
            bounding_box_min = [
                round(self.v_min.x + (self.v_max.x - self.v_min.x) * 2 / 3, 3),
                y - 0.1 * self.refine_size,
                self.v_min.z
            ]
            bounding_box_max = [
                self.v_max.x,
                y + 0.1 * self.refine_size,
                self.v_max.z
            ]
        elif orientation == 90 or orientation == 270:
            bounding_box_min = [
                x - 0.1 * self.refine_size,
                round(self.v_min.y + (self.v_max.y - self.v_min.y) * 2 / 3, 3),
                self.v_min.z
            ]
            bounding_box_max = [
                x + 0.1 * self.refine_size,
                self.v_max.y,
                self.v_max.z
            ]
        else:
            raise ValueError(f"Invalid orientation: {orientation} for rack '{self.config.uid}'")

        return bounding_box_min, bounding_box_max

    def make_cyclic_patch(self):
        orientation = self.config.geometry.orientation
        if orientation in [0, 180]:
            y_inlet_face = self.v_min.y if orientation == 0 else self.v_max.y
            y_outlet_face = self.v_max.y if orientation == 0 else self.v_min.y
            x_inlet_face = None
            x_outlet_face = None
        else:  # orientation in [90, 270]
            y_inlet_face = None
            y_outlet_face = None
            x_inlet_face = self.v_max.x if orientation == 90 else self.v_min.x
            x_outlet_face = self.v_min.x if orientation == 90 else self.v_max.x

        bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(x=x_inlet_face, y=y_inlet_face)
        self.rack_cyclic_patch_list.append(
            PatchModel(
                name=f"rack_cyclic_{self.config.uid}_master",
                neighbour_patch_name=f"rack_cyclic_{self.config.uid}_slave",
                bounding_box_max=bounding_box_max,
                bounding_box_min=bounding_box_min
            )
        )

        bounding_box_min, bounding_box_max = self._get_bounding_box_min_max(x=x_outlet_face, y=y_outlet_face)
        self.rack_cyclic_patch_list.append(
            PatchModel(
                name=f"rack_cyclic_{self.config.uid}_slave",
                neighbour_patch_name=f"rack_cyclic_{self.config.uid}_master",
                bounding_box_max=bounding_box_max,
                bounding_box_min=bounding_box_min
            )
        )

    def cheek_config(self: [Rack, RowRackModel]):
        if not (self.config.geometry.orientation == 0 or self.config.geometry.orientation == 90 or
                self.config.geometry.orientation == 180 or self.config.geometry.orientation == 270):
            raise ValueError(f"Invalid orientation: {self.config.geometry.orientation} for rack '{self}'")

        if self.config.geometry.size.z < self.config.geometry.slot * self.slot_height:
            raise ValueError(
                f"Invalid Rack height for '{self.config.uid}': "
                f"actual {self.config.geometry.size.z} is less than required "
                f"{self.config.geometry.slot * self.slot_height} "
                f"(slots: {self.config.geometry.slot}, slot height: {self.slot_height})"
            )

    def _make_surrounding_plane(self):
        orientation = self.config.geometry.orientation
        if orientation == 0 or orientation == 180:
            self.surrounding_planes = [
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_left_plane",
                    origin=[self.v_min.x if orientation == 0 else self.v_max.x, self.v_min.y, self.v_min.z],
                    span=[0, self.config.geometry.size.y, self.config.geometry.size.z],
                ),
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_right_plane",
                    origin=[self.v_max.x if orientation == 0 else self.v_min.x, self.v_min.y, self.v_min.z],
                    span=[0, self.config.geometry.size.y, self.config.geometry.size.z],
                ),
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_top_plane",
                    origin=[self.v_min.x, self.v_min.y, self.v_min.z + self.config.geometry.size.z],
                    span=[self.config.geometry.size.x, self.config.geometry.size.y, 0],
                )
            ]
        elif orientation == 90 or orientation == 270:
            self.surrounding_planes = [
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_left_plane",
                    origin=[self.v_min.x, self.v_min.y if orientation == 90 else self.v_max.y, self.v_min.z],
                    span=[self.config.geometry.size.y, 0, self.config.geometry.size.z],
                ),
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_right_plane",
                    origin=[self.v_min.x, self.v_max.y if orientation == 90 else self.v_min.y, self.v_min.z],
                    span=[self.config.geometry.size.y, 0, self.config.geometry.size.z],
                ),
                PlaneModel(
                    name=f"rack_wall_{self.config.uid}_top_plane",
                    origin=[self.v_min.x, self.v_min.y, self.v_min.z + self.config.geometry.size.z],
                    span=[self.config.geometry.size.y, self.config.geometry.size.x, 0],
                )
            ]

    def _make_blanking_plane(self):
        orientation = self.config.geometry.orientation
        if orientation in [0, 180]:
            origin = [self.v_min.x, self.v_min.y if orientation == 0 else self.v_max.y, self.v_min.z]
            span = [self.config.geometry.size.x, 0, self.config.geometry.size.z]
        elif orientation in [90, 270]:
            origin = [self.v_max.x if orientation == 90 else self.v_min.x, self.v_min.y, self.v_min.z]
            span = [0, self.config.geometry.size.x, self.config.geometry.size.z]
        else:
            raise ValueError(f"Got invalid rack orientation {orientation}")
        self.blanking_panel = PlaneModel(
            name=f"rack_panel_{self.config.uid}_blanking_panel",
            origin=origin,
            span=span
        )

    def _make_servers(self):
        for server_name, server in self.config.constructions.servers.items():
            if server.geometry.orientation != self.config.geometry.orientation:
                server.geometry.orientation = self.config.geometry.orientation
                logger.warning(f"Server '{server_name}' orientation is changed to {self.config.geometry.orientation}, "
                               f"because it is not the same as the rack orientation")
            orientation = server.geometry.orientation
            if orientation == 0 or orientation == 270:
                server_v_min = Vertex(
                    x=self.v_min.x,
                    y=self.v_min.y,
                    z=self.v_min.z + server.geometry.slot_position * self.slot_height
                )
                server_v_max = Vertex(
                    x=self.v_min.x + server.geometry.width
                    if self.config.geometry.orientation == 0 else self.v_min.x + server.geometry.depth,

                    y=self.v_min.y + server.geometry.depth
                    if self.config.geometry.orientation == 0 else self.v_min.y + server.geometry.width,

                    z=self.v_min.z + (
                                server.geometry.slot_position + server.geometry.slot_occupation) * self.slot_height
                )
            else:  # orientation == 90 or orientation == 180:
                server_v_min = Vertex(
                    x=self.v_max.x - server.geometry.depth
                    if orientation == 90 else self.v_min.x,

                    y=self.v_min.y if orientation == 90 else self.v_max.y - server.geometry.depth,
                    z=self.v_min.z + server.geometry.slot_position * self.slot_height
                )
                server_v_max = Vertex(
                    x=self.v_max.x,
                    y=self.v_max.y,
                    z=self.v_min.z + (
                                server.geometry.slot_position + server.geometry.slot_occupation) * self.slot_height
                )

            self.servers.append(
                ServerModel(
                    config=server,
                    v_min=server_v_min,
                    v_max=server_v_max,
                    base_size=self.base_size,
                    slot_height=self.slot_height,
                )
            )

    def _make_refinement_region(self):
        orientation = int(self.config.geometry.orientation)
        _v_min = [
            self.v_min.x if orientation in [0, 180] else self.v_min.x - self.base_size,
            self.v_min.y - self.base_size if orientation in [0, 180] else self.v_min.y,
            self.v_min.z
        ]
        _v_max = [
            self.v_max.x if orientation in [0, 180] else self.v_max.x + self.base_size,
            self.v_max.y + self.base_size if orientation in [0, 180] else self.v_max.y,
            self.v_max.z
        ]
        self.refine_region = BoxModel(
            name=f"{self.config.uid}_box",
            v_min=_v_min,
            v_max=_v_max,
            is_refinement_box=True,
            refinement_level=self.refinement_level
        )

    @property
    def snappyHex_cmd(self):
        return self.box.snappyHex_cmd

    @property
    def createBaffles_cmd(self):
        create_baffles_cmd = ""
        for plane in self.surrounding_planes:
            create_baffles_cmd += plane.createBaffles_cmd
        if self.blanking_panel:
            create_baffles_cmd += self.blanking_panel.createBaffles_cmd
        return create_baffles_cmd

    @property
    def topoSet_cmd(self):
        topo_set_cmd = ""
        for cyclic_patch in self.rack_cyclic_patch_list:
            topo_set_cmd += cyclic_patch.topoSet_cmd
        for server in self.servers:
            topo_set_cmd += server.topoSet_cmd
        return topo_set_cmd

    @property
    def createPatch_cmd(self):
        create_patch_cmd = ""
        for cyclic_patch in self.rack_cyclic_patch_list:
            create_patch_cmd += cyclic_patch.createPatch_cmd
        for server in self.servers:
            create_patch_cmd += server.createPatch_cmd
        return create_patch_cmd


class MeshBuilder:
    docker_image = "ghcr.io/cap-dcwiz/openfoam-2312-cuda-smi75:1.0.0"
    slot_height: float = 0.05  # 1U = 0.05 m
    base_size: float = 0.2  # base_size for the background blockMesh
    scale: int = 0  # scale for refinement region
    room: Room
    case_dir: Path
    process_num: int

    @property
    def command(self) -> list[str]:
        command = [
            "bash",
            "-c",
            (
                "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && "
                "blockMesh && snappyHexMesh -overwrite && createBaffles -overwrite && topoSet && createPatch -overwrite"
            ),
        ]
        return command

    def _align_geometry(self):
        """
        Round the coordinates of the geometry objects to the self.base_size size to make the geometry objects align with the
        structured grid to improve the mesh quality
        """

        def round_raise_floor_false_ceiling(raised_floor_false_ceiling):
            raised_floor_false_ceiling.geometry.height = round_to_base(raised_floor_false_ceiling.geometry.height,
                                                                       self.base_size)
            logger.debug(f"raised_floor, height = {raised_floor_false_ceiling.geometry.height}")
            for opening_id, opening in enumerate(raised_floor_false_ceiling.geometry.openings.values()):
                opening.location.x = round_to_base(opening.location.x, self.base_size)
                opening.location.y = round_to_base(opening.location.y, self.base_size)
                opening.location.z = round_to_base(opening.location.z, self.base_size)
                opening.size.x = round_to_base(opening.size.x, self.base_size)
                opening.size.y = round_to_base(opening.size.y, self.base_size)
                logger.debug(
                    f"opening-{opening_id} @ {raised_floor_false_ceiling.uid},"
                    f" location = ({opening.location.x}, {opening.location.y}),"
                    f" size = ({opening.size.x}, {opening.size.y})"
                )

        def round_box(box_model):
            box_model.geometry.location.x = round_to_base(box_model.geometry.location.x, self.base_size)
            box_model.geometry.location.y = round_to_base(box_model.geometry.location.y, self.base_size)
            box_model.geometry.location.z = round_to_base(box_model.geometry.location.z, self.base_size)
            box_model.geometry.size.x = round_to_base(box_model.geometry.size.x, self.base_size)
            box_model.geometry.size.y = round_to_base(box_model.geometry.size.y, self.base_size)
            box_model.geometry.size.z = round_to_base(box_model.geometry.size.z, self.base_size)
            logger.debug(
                f"{box_model.uid}, "
                f"location = ({box_model.geometry.location.x}, {box_model.geometry.location.y}, {box_model.geometry.location.z}),"
                f" size = ({box_model.geometry.size.x}, {box_model.geometry.size.y}, {box_model.geometry.size.z})"
            )

        def round_face(face, face_name=""):
            face.width = round_to_base(face.width, self.base_size)
            face.length = round_to_base(face.length, self.base_size)
            face.offset.x = round_to_base(face.offset.x, self.base_size)
            face.offset.y = round_to_base(face.offset.y, self.base_size)
            face.offset.z = round_to_base(face.offset.z, self.base_size)
            logger.debug(f"{face_name}, width = {face.width}, length = {face.length}, "
                         f"offset = ({face.offset.x}, {face.offset.y}, {face.offset.z})")

        def round_rack(rack):
            # round the box of the rack
            round_box(box_model=rack)

            # round the servers
            for server in rack.constructions.servers.values():
                server.geometry.depth = round_to_base(server.geometry.depth, self.base_size)
                if server.geometry.depth != rack.geometry.size.y:
                    server.geometry.depth = rack.geometry.size.y
                    logger.warning(f"Server '{server.uid}' depth is changed to {rack.geometry.size.y}, "
                                   f"because it is not the same as the rack depth")
                server.geometry.width = round_to_base(server.geometry.width, self.base_size)

        for plane in self.room.geometry.plane:
            plane.x = round_to_base(plane.x, self.base_size)
            plane.y = round_to_base(plane.y, self.base_size)
            logger.debug(f"room_plane, location = ({plane.x}, {plane.y})")

        # round the boxes
        for box in self.room.constructions.boxes.values():
            round_box(box_model=box)

        # round the acu
        for acu in self.room.constructions.acus.values():
            # round the box of the acu
            round_box(box_model=acu)

            # round the faces of the acu
            round_face(face=acu.geometry.supply_face, face_name=f"{acu.uid}_supply_face")
            round_face(face=acu.geometry.return_face, face_name=f"{acu.uid}_return_face")

        # round the rack
        if self.room.constructions.racks:
            for rack in self.room.constructions.racks.values():
                round_rack(rack)

        if self.room.constructions.rows:
            # round rows
            for row in self.room.constructions.rows.values():
                row.geometry.size.x = (round_to_base(row.geometry.size.x, self.base_size) *
                                       row.geometry.rackNum)
                row.geometry.size.y = round_to_base(row.geometry.size.y, self.base_size)
                row.geometry.size.z = round_to_base(row.geometry.size.z, self.base_size)
                row.geometry.location.x = round_to_base(row.geometry.location.x, self.base_size)
                row.geometry.location.y = round_to_base(row.geometry.location.y, self.base_size)
                row.geometry.location.z = round_to_base(row.geometry.location.z, self.base_size)
                logger.debug(
                    f"{row.uid}, "
    
                    f"location = ({row.geometry.location.x}, "
                    f"{row.geometry.location.y}, "
                    f"{row.geometry.location.z}),"
    
                    f" size = ({row.geometry.size.x}, "
                    f"{row.geometry.size.y}, "
                    f"{row.geometry.size.z})"
                )
                for rack in row.racks.values():
                    round_rack(rack)

        # round the raised floor
        if self.room.constructions.raised_floor:
            raised_floor = self.room.constructions.raised_floor
            round_raise_floor_false_ceiling(raised_floor)

        # round the false ceiling
        if self.room.constructions.false_ceiling:
            false_ceiling = self.room.constructions.false_ceiling
            round_raise_floor_false_ceiling(false_ceiling)

    def make_room(self) -> tuple[Vertex, Vertex, int, int, int]:
        """
        Create the exterior geometry of the room
        """
        min_z = 0
        v_min, v_max = Vertex(x=0, y=0, z=min_z), Vertex(x=0, y=0, z=self.room.geometry.height)
        # find the minimum and maximum x, y, and z coordinates of the room
        for vertex in self.room.geometry.plane:
            if vertex.x < v_min.x:
                v_min.x = vertex.x
            if vertex.y < v_min.y:
                v_min.y = vertex.y
            if vertex.x > v_max.x:
                v_max.x = vertex.x
            if vertex.y > v_max.y:
                v_max.y = vertex.y

        # find the number of cells in the x, y, and z directions
        x_cells = int((v_max.x - v_min.x) / self.base_size)
        if self.base_size * x_cells != (v_max.x - v_min.x):
            v_max.x = x_cells * self.base_size - v_min.x
        y_cells = int((v_max.y - v_min.y) / self.base_size)
        if self.base_size * y_cells != (v_max.y - v_min.y):
            v_max.y = y_cells * self.base_size - v_min.y
        z_cells = int((v_max.z - v_min.z) / self.base_size)
        if self.base_size * z_cells != (v_max.z - v_min.z):
            v_max.z = z_cells * self.base_size - v_min.z
        return v_min, v_max, x_cells, y_cells, z_cells

    def make_acus(self, acus: Dict[str, ACU]):
        acu_list = []
        for acu_name, acu in acus.items():
            acu_list.append(
                ACUModel(
                    acu=acu,
                    base_size=self.base_size,
                )
            )
        return acu_list

    def make_boxes(self, boxes: Dict[str, Box]):
        box_list = []
        plane_list = []
        for box_name, box in boxes.items():
            # if the box is closed, create the box object directly by specifying the min and max coordinates
            if is_closed(box):
                box_list.append(
                    BoxModel(
                        name="box_" + box_name,
                        v_min=[box.geometry.location.x, box.geometry.location.y, box.geometry.location.z],
                        v_max=[
                            box.geometry.location.x + box.geometry.size.x,
                            box.geometry.location.y + box.geometry.size.y,
                            box.geometry.location.z + box.geometry.size.z
                        ],
                        is_refinement_box=False
                    )
                )
            # if the box is not closed, create each face of the box separately
            else:
                if box.geometry.faces.bottom:
                    bottom_face_origin = [
                        box.geometry.location.x,
                        box.geometry.location.y,
                        box.geometry.location.z
                    ]
                    bottom_face_span = [
                        box.geometry.size.x,
                        box.geometry.size.y,
                        0
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_bottom_face",
                            origin=bottom_face_origin,
                            span=bottom_face_span,
                        )
                    )
                if box.geometry.faces.top:
                    top_face_origin = [
                        box.geometry.location.x,
                        box.geometry.location.y,
                        box.geometry.location.z + box.geometry.size.z
                    ]
                    top_face_span = [
                        box.geometry.size.x,
                        box.geometry.size.y,
                        0
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_top_face",
                            origin=top_face_origin,
                            span=top_face_span,
                        )
                    )
                if box.geometry.faces.left:
                    left_face_origin = [
                        box.geometry.location.x,
                        box.geometry.location.y,
                        box.geometry.location.z
                    ]
                    left_face_span = [
                        0,
                        box.geometry.size.y,
                        box.geometry.size.z
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_left_face",
                            origin=left_face_origin,
                            span=left_face_span,
                        )
                    )
                if box.geometry.faces.right:
                    right_face_origin = [
                        box.geometry.location.x + box.geometry.size.x,
                        box.geometry.location.y,
                        box.geometry.location.z
                    ]
                    right_face_span = [
                        0,
                        box.geometry.size.y,
                        box.geometry.size.z
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_right_face",
                            origin=right_face_origin,
                            span=right_face_span,
                        )
                    )
                if box.geometry.faces.front:
                    front_face_origin = [
                        box.geometry.location.x,
                        box.geometry.location.y,
                        box.geometry.location.z
                    ]
                    front_face_span = [
                        box.geometry.size.x,
                        0,
                        box.geometry.size.z
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_front_face",
                            origin=front_face_origin,
                            span=front_face_span,
                        )
                    )
                if box.geometry.faces.rear:
                    rear_face_origin = [
                        box.geometry.location.x,
                        box.geometry.location.y + box.geometry.size.y,
                        box.geometry.location.z
                    ]
                    rear_face_span = [
                        box.geometry.size.x,
                        0,
                        box.geometry.size.z
                    ]
                    plane_list.append(
                        PlaneModel(
                            name=f"box_{box_name}_rear_face",
                            origin=rear_face_origin,
                            span=rear_face_span,
                        )
                    )
        return box_list, plane_list

    def make_racks(self, racks: Dict[str, Rack], refinement_level: int = 2 ) -> List[RackModel]:
        rack_list = []
        for rack_name, rack in racks.items():
            rack_model = RackModel(
                rack=rack,
                base_size=self.base_size,
                scale=0,
                refinement_level=refinement_level
            )
            rack_list.append(rack_model)
        return rack_list

    def make_row_racks( self, rows: Dict[str, Row], refinement_level: int = 2 ) -> list[RowRackModel]:
        row_rack_list = []
        for row in rows.values():
            row_rack_model = RowRackModel(
                row_rack=row,
                base_size=self.base_size,
                scale=0,
                refinement_level=refinement_level
            )
            row_rack_list.append(row_rack_model)
        return row_rack_list

    def make_plane(
            self,
            plane: Panel,
            v_min: Vertex,
            v_max: Vertex,
            name: str
    ) -> tuple[list[PlaneModel], list[PlaneModel]]:
        main_panel_list = []
        opening_face_list = []
        if plane is not None:
            main_panel_list.append(
                PlaneModel(
                    name=f"{name}_panel",
                    origin=[v_min.x, v_min.y, plane.geometry.height],
                    span=[v_max.x - v_min.x, v_max.y - v_min.y, 0],
                )
            )
            for opening_name, opening in plane.geometry.openings.items():
                opening_face_list.append(
                    PlaneModel(
                        name=f"opening_{name}_{opening_name}",
                        origin=[opening.location.x, opening.location.y, plane.geometry.height],
                        span=[opening.size.x, opening.size.y, 0],
                    )
                )
        return main_panel_list, opening_face_list

    def write_blockMesh_dict(self, v_min, v_max, x_cells, y_cells, z_cells):
        template = template_env.get_template("foam/template/mesh/blockMeshDict.j2")
        with open(self.case_dir.joinpath("system/blockMeshDict"), "w") as f:
            f.write(
                template.render(
                    v_max=v_max,
                    v_min=v_min,
                    x_cells=x_cells,
                    y_cells=y_cells,
                    z_cells=z_cells,
                )
            )

    def write_snappyHexMesh_dict(
            self,
            snappy_obj_list: List[BoxModel],
    ):
        location = Vertex(
            x=0.,
            y=0.,
            z=0.,
        )
        snappy_obj_cmd = ""
        refinement_surfaces_cmd = ""
        refinement_regions_cmd = ""
        for obj in snappy_obj_list:
            snappy_obj_cmd += f"{obj.snappyHex_cmd[0]}"
            refinement_surfaces_cmd += f"{obj.snappyHex_cmd[1]}"
            refinement_regions_cmd += f"{obj.snappyHex_cmd[2]}"

        template = template_env.get_template("foam/template/mesh/snappyHexMeshDict.j2")
        with open(self.case_dir.joinpath("system/snappyHexMeshDict"), "w") as f:
            f.write(
                template.render(
                    snappy_obj_cmd=snappy_obj_cmd,
                    refinement_surfaces_cmd=refinement_surfaces_cmd,
                    refinement_regions_cmd=refinement_regions_cmd,
                    location=location,
                )
            )

    def write_createBaffles_dict(
            self,
            plane_list: List[PlaneModel]
    ):
        baffles_cmd = ""
        for plane in plane_list:
            baffles_cmd += plane.createBaffles_cmd
        template = template_env.get_template("foam/template/mesh/createBafflesDict.j2")
        with open(self.case_dir.joinpath("system/createBafflesDict"), "w") as f:
            f.write(
                template.render(
                    baffles_cmd=baffles_cmd,
                )
            )

    def write_createPatch_dict(
            self,
            patch_list: List[ACUModel | RackModel]
    ):
        patches_cmd = ""
        for patch in patch_list:
            patches_cmd += patch.createPatch_cmd
        template = template_env.get_template("foam/template/mesh/createPatchDict.j2")
        with open(self.case_dir.joinpath("system/createPatchDict"), "w") as f:
            f.write(
                template.render(
                    patches_cmd=patches_cmd
                )
            )

    def write_topoSet_dict(
            self,
            face_set_list: List[ACUModel | RackModel]
    ):
        face_set_cmd = ""
        for face_set in face_set_list:
            face_set_cmd += face_set.topoSet_cmd
        template = template_env.get_template("foam/template/mesh/topoSetDict.j2")
        with open(self.case_dir.joinpath("system/topoSetDict"), "w") as f:
            f.write(
                template.render(
                    face_set_cmd=face_set_cmd,
                )
            )

    def run(
            self,
            room: Room,
            case_dir: Path = Path("log/base"),
            process_num: int = 1,
            refinement_level: int = 2,
    ):
        self.room = room
        self.case_dir = case_dir
        self.process_num = process_num
        self._align_geometry()

        # Make objects in the room (e.g., ceiling, raised floor, rack, etc.)
        raised_floor = self.room.constructions.raised_floor
        false_ceiling = self.room.constructions.false_ceiling
        boxes = self.room.constructions.boxes
        acus = self.room.constructions.acus
        racks = self.room.constructions.racks
        rows = self.room.constructions.rows

        # make geometry objects
        v_min, v_max, x_cells, y_cells, z_cells = self.make_room()
        raised_floor, raised_floor_opening_face_list = self.make_plane(
            name="raised_floor",
            plane=raised_floor,
            v_min=v_min,
            v_max=v_max,
        )
        false_ceiling, false_ceiling_opening_face_list = self.make_plane(
            name="false_ceiling",
            plane=false_ceiling,
            v_min=v_min,
            v_max=v_max,
        )
        box_list, box_plane_list = self.make_boxes(boxes=boxes)
        acu_list = self.make_acus(acus=acus)
        rack_list = self.make_racks(racks=racks, refinement_level=refinement_level)
        row_racks_list = self.make_row_racks(rows=rows, refinement_level=refinement_level)

        # write the block mesh file
        self.write_blockMesh_dict(
            v_min=v_min,
            v_max=v_max,
            x_cells=x_cells,
            y_cells=y_cells,
            z_cells=z_cells,
        )
        # write snappyHexMesh dict
        self.write_snappyHexMesh_dict(
            snappy_obj_list=box_list + acu_list + rack_list + row_racks_list,
        )
        # write createBaffles dict
        self.write_createBaffles_dict(
            plane_list=raised_floor + false_ceiling + box_plane_list + rack_list + row_racks_list +
                       false_ceiling_opening_face_list + raised_floor_opening_face_list,
        )
        # write topoSet dict
        self.write_topoSet_dict(
            face_set_list=acu_list + rack_list + row_racks_list,
        )
        # write createPatch dict
        self.write_createPatch_dict(
            patch_list=acu_list + rack_list + row_racks_list
        )

        self.run_container(user=0, case_dir=self.case_dir)

        logger.info("***** Mesh finished *****\n\n")


class SnappyHexBackend(MeshBuilder, DockerBackend):
    pass


class SnappyHexK8sBackend(MeshBuilder, K8sBackend):
    pass