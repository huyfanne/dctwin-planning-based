from dclib.ite.servers.server import Server
from utils import rotate_rectangular
from typing import Dict, List
from pathlib import Path
from loguru import logger
from jinja2 import Environment, FileSystemLoader
from dclib import Room
from dclib.construction.surfaces import Panel
from dclib.cooling.room.facilities import ACU
from dclib.construction.entities import Box
from dclib.ite.racks import Rack
from dclib.models.geometry import Vertex
from utils import is_closed, round_to_base
from dctwin.utils import (
    template_env,
    template_dir,
    config,
)
from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s


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
        return f"""
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
        return f"""
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

    @property
    def createPatch_cmd(self):
        return f"""
        {{
            name {self.patch_name};
            patchInfo
            {{
                type patch;
            }}
            constructFrom set;
            set {self.face_set_name};
        }}
        {{
            name {self.patch_name};
            patchInfo
            {{
                type cyclic;
            }}
            constructFrom set;
            set {self.face_set_name};
        }}
        """


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
            name=f"acu_box_{self.config.uid}",
            v_min=[v_min.x, v_min.y, v_min.z],
            v_max=[v_max.x, v_max.y, v_max.z],
            is_refinement_box=False
        )

    def _make_supply_face(self):
        acu_supply_face = self.config.geometry.supply_face
        bounding_box_min, bounding_box_max = self._get_supply_or_return_face_bounding_box(face=acu_supply_face)
        self.supply_face = PatchModel(
            name=f"acu_supply_face_{self.config.uid}",
            bounding_box_min=bounding_box_min,
            bounding_box_max=bounding_box_max
        )

    def _make_return_face(self):
        acu_return_face = self.config.geometry.return_face
        bounding_box_min, bounding_box_max = self._get_supply_or_return_face_bounding_box(face=acu_return_face)
        self.return_face = PatchModel(
            name=f"acu_return_face_{self.config.uid}",
            bounding_box_min=bounding_box_min,
            bounding_box_max=bounding_box_max
        )

    def _get_supply_or_return_face_bounding_box(self, face):
        if face.side.name == "bottom" or face.side.name == "top":
            if self.config.geometry.orientation == 0 or self.config.geometry.orientation == 180:
                bounding_box_min = [
                    self.box.v_min[0] + face.offset.x,
                    self.box.v_min[1] + face.offset.y,
                    self.box.v_min[2] - 0.1 * self.base_size if face.side.name == "bottom"
                    else self.box.v_min[2] + self.config.geometry.size.z - 0.1 * self.base_size
                ]
                bounding_box_max = [
                    self.box.v_min[0] + face.offset.x + face.width,
                    self.box.v_min[1] + face.offset.y + face.length,
                    self.box.v_min[2] + 0.1 * self.base_size if face.side.name == "bottom"
                    else self.box.v_min[2] + self.config.geometry.size.z - 0.1 * self.base_size
                ]
            else:
                bounding_box_min = [
                    self.box.v_min[0] + face.offset.y,
                    self.box.v_min[1] + face.offset.x,
                    self.box.v_min[2] - 0.1 * self.base_size if face.side.name == "bottom"
                    else self.box.v_min[2] + self.config.geometry.size.z - 0.1 * self.base_size
                ]
                bounding_box_max = [
                    self.box.v_min[0] + face.offset.y + face.length,
                    self.box.v_min[1] + face.offset.x + face.width,
                    self.box.v_min[2] + 0.1 * self.base_size if face.side.name == "bottom"
                    else self.box.v_min[2] + self.config.geometry.size.z - 0.1 * self.base_size
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
                    else self.box.v_min[0] + self.config.geometry.size.x - 0.1 * self.base_size,
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
                    else self.box.v_min[1] + self.config.geometry.size.y - 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
        else:   # face.side.name == "front" or face.side.name == "rear":
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
                    else self.box.v_min[1] + self.config.geometry.size.y - 0.1 * self.base_size,
                    self.box.v_min[2] + face.offset.y + face.length
                ]
            else:
                bounding_box_min = [
                    self.box.v_min[0] - 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 90)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 270)
                    else self.box.v_min[0] + self.config.geometry.size.x - 0.1 * self.base_size,
                    self.box.v_min[1] + face.offset.x,
                    self.box.v_min[2] + face.offset.y
                ]
                bounding_box_max = [
                    self.box.v_min[0] + 0.1 * self.base_size
                    if (face.side.name == "front" and self.config.geometry.orientation == 90)
                       or (face.side.name == "rear" and self.config.geometry.orientation == 270)
                    else self.box.v_min[0] + self.config.geometry.size.x - 0.1 * self.base_size,
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
        self.refine_size = base_size / (2**scale)
        self._make_box()
        self._make_inlet_face()
        self._make_outlet_face()

    def _make_box(self):
        server_slot = self.config.geometry.slot_position
        server_slot_occupation = self.config.geometry.slot_occupation
        server_height = server_slot_occupation * self.slot_height
        server_location = Vertex(
            x=self.v_min.x,
            y=self.v_min.y,
            z=self.v_min.z + server_slot * self.slot_height
        )
        server_size = Vertex(
            x=self.config.geometry.width,
            y=self.config.geometry.depth,
            z=server_height
        )
        self.box = BoxModel(
            name=f'server_box_{self.config.uid}',
            v_min=[
                server_location.x,
                server_location.y,
                server_location.z
            ],
            v_max=[
                server_location.x + server_size.x,
                server_location.y + server_size.y,
                server_location.z + server_size.z
            ],
            is_refinement_box=False
        )

    def _make_inlet_face(self):
        orientation = self.config.geometry.orientation
        server_inlet_face = self.config.geometry.inlet_face
        server_height = self.config.geometry.slot_occupation * self.slot_height
        server_size = Vertex(
            x=self.config.geometry.width,
            y=self.config.geometry.depth,
            z=server_height
        )
        if (server_inlet_face == 'front' or server_inlet_face is None) and orientation == 0:
            bounding_box_min = [
                self.v_min.x,
                self.v_min.y - 0.1 * self.refine_size,
                self.v_min.z
            ]
            bounding_box_max = [
                self.box.v_min[0] + server_size.x,
                self.box.v_min[1] + 0.1 * self.refine_size,
                self.box.v_min[2] + server_size.z
            ]
        else:
            bounding_box_min = []
            bounding_box_max = []
        self.inlet_face = PatchModel(
            name=f"server_inlet_{self.config.uid}",
            neighbour_patch_name=f"server_outlet_{self.config.uid}",
            bounding_box_max=bounding_box_max,
            bounding_box_min=bounding_box_min
        )

    def _make_outlet_face(self):
        orientation = self.config.geometry.orientation
        server_outlet_face = self.config.geometry.outlet_face
        server_height = self.config.geometry.slot_occupation * self.slot_height
        server_size = Vertex(
            x=self.config.geometry.width,
            y=self.config.geometry.depth,
            z=server_height
        )
        if (server_outlet_face == 'rear' or server_outlet_face is None) and orientation == 0:
            bounding_box_min = [
                self.v_min.x,
                self.v_min.y + server_size.y - 0.1 * self.refine_size,
                self.v_min.z
            ]
            bounding_box_max = [
                self.box.v_min[0] + server_size.x,
                self.box.v_min[1] + server_size.y + 0.1 * self.refine_size,
                self.box.v_min[2] + server_size.z
            ]
        else:
            bounding_box_min = []
            bounding_box_max = []
        self.outlet_face = PatchModel(
            name=f"server_outlet_{self.config.uid}",
            neighbour_patch_name=f"server_inlet_{self.config.uid}",
            bounding_box_max=bounding_box_max,
            bounding_box_min=bounding_box_min
        )

    @property
    def snappyHex_cmd(self):
        return self.box.snappyHex_cmd

    @property
    def topoSet_cmd(self):
        return self.inlet_face.topoSet_cmd + self.outlet_face.topoSet_cmd

    @property
    def createPatch_cmd(self):
        return self.inlet_face.createPatch_cmd + self.outlet_face.createPatch_cmd

class RackModel:
    config: Rack
    v_min: Vertex
    v_max: Vertex
    base_size: float
    refine_size: float

    def __init__(
        self,
        rack: Rack,
        base_size: float = 0.2,
        scale: int = 0
    ):
        self.config = rack
        self.base_size = base_size
        self.refine_size = base_size / (2**scale)
        self.refine_region = None
        self.servers = []
        self.surrounding_planes = []
        self.blanking_panel = None
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
        # make the surrounding planes of the rack
        self._make_surrounding_plane()
        # make the blanking panel of the rack
        if rack.geometry.has_blanking_panel:
             self._make_blanking_plane()
        # make the servers of the rack
        self._make_servers()
        # make the refinement region of the rack
        self._make_refinement_region()

    def _make_surrounding_plane(self):
        self.surrounding_planes = [
            PlaneModel(
                name=f"rack_wall_{self.config.uid}_left_plane",
                origin=[self.v_min.x, self.v_min.y, self.v_min.z],
                span=[0, self.config.geometry.size.y, self.config.geometry.size.z],
            ),
            PlaneModel(
                name=f"rack_wall_{self.config.uid}_right_plane",
                origin=[self.v_max.x, self.v_min.y, self.v_min.z],
                span=[0, self.config.geometry.size.y, self.config.geometry.size.z],
            ),
            PlaneModel(
                name=f"rack_wall_{self.config.uid}_top_plane",
                origin=[self.v_min.x, self.v_min.y, self.v_min.z + self.config.geometry.size.z],
                span=[self.config.geometry.size.x, self.config.geometry.size.y, 0],
            )
        ]

    def _make_blanking_plane(self):
        if self.config.geometry.orientation in [0, 180]:
            span = [self.config.geometry.size.x, 0, self.config.geometry.size.z]
        elif self.config.geometry.orientation in [90, 270]:
            span = [0, self.config.geometry.size.y, self.config.geometry.size.z]
        else:
            raise ValueError(f"Got invalid rack orientation {self.config.geometry.orientation}")
        self.blanking_panel = PlaneModel(
            name=f"rack_panel_{self.config.uid}_blanking_panel",
            origin=[self.v_min.x, self.v_min.y, self.v_min.z],
            span=span
        )

    def _make_servers(self):
        for server_name, server in self.config.constructions.servers.items():
            server_v_min = self.v_min
            server_v_max = Vertex(
                x=self.v_min.x + server.geometry.width,
                y=self.v_min.y + server.geometry.depth,
                z=self.v_min.z + (server.geometry.slot_position + server.geometry.slot_occupation) * 0.05
            )
            self.servers.append(
                ServerModel(
                    config=server,
                    v_min=server_v_min,
                    v_max=server_v_max,
                    base_size=self.base_size
                )
            )

    def _make_refinement_region(self):
        if self.config.geometry.orientation == 0 or self.config.geometry.orientation == 180:
            _v_min = [
                self.config.geometry.location.x,
                self.config.geometry.location.y - self.base_size,
                self.config.geometry.location.z
            ]
            _v_max = [
                self.config.geometry.location.x + self.config.geometry.size.x,
                self.config.geometry.location.y + self.config.geometry.size.y + self.base_size,
                self.config.geometry.location.z + self.config.geometry.size.z
            ]
        elif self.config.geometry.orientation == 90 or self.config.geometry.orientation == 270:
            _v_min = [
                self.config.geometry.location.x - self.base_size,
                self.config.geometry.location.y,
                self.config.geometry.location.z
            ]
            _v_max = [
                self.config.geometry.location.x + self.config.geometry.size.x + self.base_size,
                self.config.geometry.location.y + self.config.geometry.size.y,
                self.config.geometry.location.z + self.config.geometry.size.z
            ]
        else:
            _v_min = []
            _v_max = []
            raise ValueError(
                f"Invalid orientation: {self.config.geometry.orientation} for rack '{self}'")

        self.refine_region = BoxModel(
            name=f"{self.config.uid}_box",
            v_min=_v_min,
            v_max=_v_max,
            is_refinement_box=True,
            refinement_level=2
        )

    @property
    def snappyHex_cmd(self):
        searchable_box_cmd = ""
        refinement_surface_cmd = ""
        refinement_box_cmd = ""
        for server in self.servers:
            searchable_box_cmd += server.snappyHex_cmd[0]
            refinement_surface_cmd += server.snappyHex_cmd[1]
        if self.refine_region:
            searchable_box_cmd += self.refine_region.snappyHex_cmd[0]
            refinement_box_cmd += self.refine_region.snappyHex_cmd[2]
        return searchable_box_cmd, refinement_surface_cmd, refinement_box_cmd

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
        for server in self.servers:
            topo_set_cmd += server.topoSet_cmd
        return topo_set_cmd

    @property
    def createPatch_cmd(self):
        create_patch_cmd = ""
        for server in self.servers:
            create_patch_cmd += server.createPatch_cmd
        return create_patch_cmd

class MeshBuilder:

    docker_image = "ghcr.io/cap-dcwiz/openfoam-2312-cuda-smi75:1.0.0"
    slot_height: float = 0.05  # 1U = 0.05 mm
    base_size: float = 0.2  # base_size for the background blockMesh
    scale: int = 0  # scale for refinement region
    room: Room
    case_dir: Path
    process_num: int

    @property
    def command(self) -> list[str]:
        if self.process_num > 1:
            topo_set_command = ""
            # if len(self.perforated_openings) > 0:
            #     topo_set_command = "topoSet &&"

            command = [
                "bash",
                "-c",
                (
                    "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && "
                    "blockMesh && surfaceFeatureExtract && "
                    "decomposePar -copyZero -force && "
                    "mpirun --use-hwthread-cpus --allow-run-as-root -np "
                    f"{self.process_num} snappyHexMesh -parallel -overwrite && "
                    "reconstructParMesh -constant -mergeTol 6 && "
                    f"{topo_set_command}"
                    "createPatch -overwrite && "
                    "rm -rf /data/constant/triSurface/*.eMesh && "
                    "rm -rf /data/processor* &&"
                    "checkMesh -allGeometry -allTopology"
                ),
            ]
            # command=["bash", "-c", f"sleep infinity"]
        else:
            command = [
                "bash",
                "-c",
                (
                    "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && "
                    "blockMesh && snappyHexMesh -overwrite && createBaffles -overwrite && topoSet && "
                    "createPatch -overwrite"
                ),
            ]

        return command

    def _align_geometry(self):
        """
        Round the coordinates of the geometry objects to the self.base_size size to make the geometry objects align with the
        structured grid to improve the mesh quality
        """
        for plane in self.room.geometry.plane:
            plane.x = round_to_base(plane.x, self.base_size)
            plane.y = round_to_base(plane.y, self.base_size)
            logger.debug(f"plane, location = ({plane.x}, {plane.y})")

        for box in self.room.constructions.boxes.values():
            box.geometry.location.x = round_to_base(box.geometry.location.x, self.base_size)
            box.geometry.location.y = round_to_base(box.geometry.location.y, self.base_size)
            box.geometry.location.z = round_to_base(box.geometry.location.z, self.base_size)
            box.geometry.size.x = round_to_base(box.geometry.size.x, self.base_size)
            box.geometry.size.y = round_to_base(box.geometry.size.y, self.base_size)
            box.geometry.size.z = round_to_base(box.geometry.size.z, self.base_size)
            logger.debug(
                f"{box.uid}, "
                f"location = ({box.geometry.location.x}, {box.geometry.location.y}, {box.geometry.location.z}),"
                f" size = ({box.geometry.size.x}, {box.geometry.size.y}, {box.geometry.size.z})"
            )

        # round the acu
        for acu in self.room.constructions.acus.values():
            acu.geometry.location.x = round_to_base(acu.geometry.location.x, self.base_size)
            acu.geometry.location.y = round_to_base(acu.geometry.location.y, self.base_size)
            acu.geometry.location.z = round_to_base(acu.geometry.location.z, self.base_size)
            acu.geometry.size.x = round_to_base(acu.geometry.size.x, self.base_size)
            acu.geometry.size.y = round_to_base(acu.geometry.size.y, self.base_size)
            acu.geometry.size.z = round_to_base(acu.geometry.size.z, self.base_size)
            logger.debug(
                f"{acu.uid},"
                f" location = ({acu.geometry.location.x}, {acu.geometry.location.y}, {acu.geometry.location.z}),"
                f" size = ({acu.geometry.size.x}, {acu.geometry.size.y}, {acu.geometry.size.z})"
            )

        # round the rack
        for rack in self.room.constructions.racks.values():
            rack.geometry.location.x = round_to_base(rack.geometry.location.x, self.base_size)
            rack.geometry.location.y = round_to_base(rack.geometry.location.y, self.base_size)
            rack.geometry.location.z = round_to_base(rack.geometry.location.z, self.base_size)
            rack.geometry.size.x = round_to_base(rack.geometry.size.x, self.base_size)
            rack.geometry.size.y = round_to_base(rack.geometry.size.y, self.base_size)
            rack.geometry.size.z = round_to_base(rack.geometry.size.z, self.base_size)
            logger.debug(
                f"{rack.uid},"
                f" location = ({rack.geometry.location.x}, {rack.geometry.location.y}, {rack.geometry.location.z}),"
                f" size = ({rack.geometry.size.x}, {rack.geometry.size.y}, {rack.geometry.size.z})"
            )

        # round the raised floor
        if self.room.constructions.raised_floor:
            raised_floor = self.room.constructions.raised_floor
            raised_floor.geometry.height = round_to_base(raised_floor.geometry.height, self.base_size)
            logger.debug(f"raised_floor, height = {raised_floor.geometry.height}")
            for opening_id, opening in enumerate(raised_floor.geometry.openings.values()):
                opening.location.x = round_to_base(opening.location.x, self.base_size)
                opening.location.y = round_to_base(opening.location.y, self.base_size)
                opening.size.x = round_to_base(opening.size.x, self.base_size)
                opening.size.y = round_to_base(opening.size.y, self.base_size)
                logger.debug(
                    f"opening-{opening_id} @ {raised_floor.uid},"
                    f" location = ({opening.location.x}, {opening.location.y}),"
                    f" size = ({opening.size.x}, {opening.size.y})"
                )

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

    def make_racks(
        self,
        racks: Dict[str, Rack]
    ) -> List[RackModel]:
        rack_list = []
        for rack_name, rack in racks.items():
            rack_model = RackModel(
                rack=rack,
                base_size=self.base_size,
                scale=0,
            )
            rack_list.append(rack_model)
        return rack_list

    def make_plane(
        self,
        plane: Panel,
        v_min: Vertex,
        v_max: Vertex,
        name: str
    ) -> tuple[List[PlaneModel], List[PatchModel]]:
        main_panel_list = []
        opening_face_list = []
        if plane is not None:
            main_panel_list.append(
                PlaneModel(
                    name=f"{name}_panel",
                    origin=[v_min.x, v_min.y, plane.geometry.height],
                    span=[v_max.x, v_max.y, 0],
                )
            )
            for opening_name, opening in plane.geometry.openings.items():
                opening_face_list.append(
                    PatchModel(
                        name=f"opening_{name}_{opening_name}",
                        bounding_box_min=[
                            opening.location.x,
                            opening.location.y,
                            plane.geometry.height - 0.1 * self.base_size
                        ],
                        bounding_box_max=[
                            opening.location.x + opening.size.x,
                            opening.location.y + opening.size.y,
                            plane.geometry.height + 0.1 * self.base_size
                        ]
                    )
                )
        return main_panel_list, opening_face_list

    def write_blockMesh_dict(self, v_min, v_max, x_cells, y_cells, z_cells):
        template = template_env.get_template("foam/mesh/blockMeshDict.j2")
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

        template = template_env.get_template("foam/mesh/snappyHexMeshDict.j2")
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
        template = template_env.get_template("foam/mesh/createBafflesDict.j2")
        with open(self.case_dir.joinpath("system/createBafflesDict"), "w") as f:
            f.write(
                template.render(
                    baffles_cmd=baffles_cmd,
                )
            )

    def write_createPatch_dict(
        self,
        patch_list: List[PatchModel]
    ):
        patches_cmd = ""
        for patch in patch_list:
            patches_cmd += patch.createPatch_cmd
        template = template_env.get_template("foam/mesh/createPatchDict.j2")
        with open(self.case_dir.joinpath("system/createPatchDict"), "w") as f:
            f.write(
                template.render(
                    patches_cmd=patches_cmd
                )
            )

    def write_topoSet_dict(
        self,
        face_set_list: List[PatchModel]
    ):
        face_set_cmd = ""
        for face_set in face_set_list:
            face_set_cmd += face_set.topoSet_cmd
        template = template_env.get_template("foam/mesh/topoSetDict.j2")
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
        rack_list =  self.make_racks(racks=racks)

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
            snappy_obj_list=box_list + acu_list + rack_list,
        )
        # write createBaffles dict
        self.write_createBaffles_dict(
            plane_list=raised_floor + false_ceiling + box_plane_list + rack_list,
        )
        # write topoSet dict
        self.write_topoSet_dict(
            face_set_list=acu_list + raised_floor_opening_face_list + false_ceiling_opening_face_list + rack_list,
        )
        # write createPatch dict
        self.write_createPatch_dict(
            patch_list=acu_list + raised_floor_opening_face_list + false_ceiling_opening_face_list + rack_list
        )

        self.run_container(user=0, case_dir=self.case_dir)

        logger.info("***** Mesh finished *****\n\n")


class SnappyHexBackend(MeshBuilder, Backend):
    pass


class SnappyHexBackendK8s(MeshBuilder, BackendK8s):
    pass