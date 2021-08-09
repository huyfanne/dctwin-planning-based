# pylava:skip=1
import json
import math
import os
from pathlib import Path

try:
    import salome

    salome.salome_init()
    import GEOM
    import SALOMEDS
    import SMESH
    from salome.geom import geomBuilder
    from salome.smesh import smeshBuilder

    geompy = geomBuilder.New()
    smesh = smeshBuilder.New()
except ImportError:
    raise

# Init
SRC_PATH = Path(os.getcwd(), "scripts/room.json")
if os.getenv("SRC_PATH"):
    SRC_PATH = os.getenv("SRC_PATH")
OUTPUT_PATH = Path(os.getcwd(), "output")
if os.getenv("OUTPUT_PATH"):
    OUTPUT_PATH = os.getenv("OUTPUT_PATH")
IGNORE_SERVER = os.getenv("IGNORE_SERVER", False)
SKIP_PRE_MESH = False
SAVE_HDF = os.getenv("SAVE_HDF", False)

with open(SRC_PATH) as f:
    room = json.load(f)


class SalomeUtil:
    _SORTED_SUB_FACE_INDICES = {
        "front": 1,
        "rear": 4,
        "left": 0,
        "right": 5,
        "bottom": 2,
        "top": 3,
    }
    SUB_FACE_INDICES = {
        "left": 0,
        "right": 1,
        "front": 2,
        "rear": 3,
        "bottom": 4,
        "top": 5,
    }
    SUB_FACE_SIZE_INDICES = {
        "front": ["dx", "dz"],
        "rear": ["dx", "dz"],
        "left": ["dy", "dz"],
        "right": ["dy", "dz"],
        "bottom": ["dx", "dy"],
        "top": ["dx", "dy"],
    }

    def __init__(self, skip_pre_mesh=False):
        self.geom = geompy
        self.smesh = smesh
        self.base_lcs = self.geom.MakeMarker(0, 0, 0, 1, 0, 0, 0, 1, 0)
        self.skip_pre_mesh = skip_pre_mesh

    def move_placement(self, obj, placement):
        new_cs = geompy.MakeMarker(
            placement["x"], placement["y"], placement["z"], 1, 0, 0, 0, 1, 0
        )
        return geompy.MakePosition(obj, self.base_lcs, new_cs)

    def make_box(self, size, placement=None):
        box = self.geom.MakeBoxDXDYDZ(size["dx"], size["dy"], size["dz"])
        if placement is not None:
            return self.move_placement(box, placement)
        return box

    def generate_stl(self, box, group_id: str):
        group = self.geom.CreateGroup(box, self.geom.ShapeType["FACE"])
        self.geom.UnionIDs(
            group, self.geom.SubShapeAllIDs(box, self.geom.ShapeType["FACE"])
        )
        self.geom.addToStudy(group, group_id)

        file_stl = Path(OUTPUT_PATH, f"{group_id}.stl")
        self.geom.ExportSTL(group, str(file_stl), False)

    def sub_face_ids(self, geom_obj):
        return self.geom.SubShapeAllIDs(geom_obj, self.geom.ShapeType["FACE"])

    def group_by_faces(self, geom_obj, exclude=None):
        group = self.geom.CreateGroup(geom_obj, self.geom.ShapeType["FACE"])
        face_ids = self.sub_face_ids(geom_obj)
        if exclude is not None:
            exclude_indices = [self.SUB_FACE_INDICES[i] for i in exclude]
            face_ids = [
                face_ids[i] for i, _ in enumerate(face_ids) if i not in exclude_indices
            ]
        self.geom.UnionIDs(group, face_ids)
        return group

    def sub_faces(self, geom_obj, exclude=None):
        face_ids = self.sub_face_ids(geom_obj)
        if exclude is not None:
            exclude_indices = [self.SUB_FACE_INDICES[i] for i in exclude]
            face_ids = [i for i, _ in enumerate(face_ids) if i not in exclude_indices]
        shapes = list()
        for face_id in face_ids:
            shapes.append(self.geom.GetSubShape(geom_obj, [face_id]))
        return shapes

    def sub_face(self, geom_obj, side):
        return self.geom.GetSubShape(
            geom_obj,
            [self.sub_face_ids(geom_obj)[self.SUB_FACE_INDICES[side]]],
        )

    def mesh(self, obj, min_size: float, max_size: float):
        if self.skip_pre_mesh:
            # self.geom.addToStudy(obj, name)
            return
        mesh_obj = smesh.Mesh(obj)
        netgen_1d_2d = mesh_obj.Triangle(algo=smeshBuilder.NETGEN_1D2D)
        netgen_2d_parameters_1 = netgen_1d_2d.Parameters()
        netgen_2d_parameters_1.SetMaxSize(min_size)
        netgen_2d_parameters_1.SetMinSize(max_size)
        netgen_2d_parameters_1.SetSecondOrder(0)
        netgen_2d_parameters_1.SetOptimize(1)
        netgen_2d_parameters_1.SetFineness(2)
        netgen_2d_parameters_1.SetChordalError(-1)
        netgen_2d_parameters_1.SetChordalErrorEnabled(0)
        netgen_2d_parameters_1.SetUseSurfaceCurvature(1)
        netgen_2d_parameters_1.SetFuseEdges(1)
        netgen_2d_parameters_1.SetUseDelauney(0)
        netgen_2d_parameters_1.SetQuadAllowed(0)
        netgen_2d_parameters_1.SetWorstElemMeasure(0)
        netgen_2d_parameters_1.SetCheckChartBoundary(136)
        is_done = mesh_obj.Compute()
        if is_done:
            return mesh_obj
        # if is_done:
        # self.export_stl(mesh_obj, name)

    def copy_mesh(self, name, mesh_obj, placement, orientation=0, is_export=True):
        new_mesh_obj = mesh_obj.TranslateObjectMakeMesh(
            mesh_obj, [placement["x"], placement["y"], placement["z"]], 0, name
        )
        if orientation != 0:
            new_mesh_obj.RotateObject(
                new_mesh_obj,
                SMESH.AxisStruct(
                    placement["x"], placement["y"], placement["z"], 0, 0, 1
                ),
                math.pi * orientation / 180,
                0,
            )
        if is_export:
            self.export_stl(new_mesh_obj, name)
        else:
            return new_mesh_obj

    def export_stl(self, mesh, name):
        if SAVE_HDF:
            self.smesh.SetName(mesh.GetMesh(), name)
        try:
            mesh.ExportSTL(str(Path(OUTPUT_PATH, f"{name}.stl")), 1)
        except Exception as e:
            print("ExportPartToSTL() failed. Invalid file name?", name)
            print("Exception", e)


util = SalomeUtil()


class ACUModel:
    size: dict
    supply_data: dict
    return_data: dict
    is_meshed: bool

    @classmethod
    def from_dict(cls, acu_model_data: dict):
        obj = cls()
        obj.size = acu_model_data["size"]
        obj.supply_data = acu_model_data["supply_face"]
        obj.return_data = acu_model_data["return_face"]
        obj.is_meshed = False
        return obj

    @staticmethod
    def make_sub_face(box, group, data: dict):
        face = util.sub_face(box, data["side"])
        if data["side"] in ("top", "bottom"):
            face = util.geom.MakeFaceObjHW(face, data["width"], data["length"])
        else:
            face = util.geom.MakeFaceObjHW(face, data["length"], data["width"])
        face = util.move_placement(face, data["offset"])
        group = util.geom.MakeCutList(group, [face], True)
        return group, face

    def mesh(self):
        box = util.make_box(self.size)
        group = util.group_by_faces(box)

        group, supply_face = self.make_sub_face(box, group, self.supply_data)
        group, return_face = self.make_sub_face(box, group, self.return_data)
        self.supply_mesh = util.mesh(supply_face, 0.1, 5)
        self.return_mesh = util.mesh(return_face, 0.1, 5)
        self.wall_mesh = util.mesh(group, 0.1, 5)
        self.is_meshed = True

    def make_acu(self, acu_id, placement, orientation):
        if self.is_meshed is False:
            self.mesh()
        util.copy_mesh(f"acu_supply_{acu_id}", self.supply_mesh, placement, orientation)
        util.copy_mesh(f"acu_return_{acu_id}", self.return_mesh, placement, orientation)
        util.copy_mesh(f"acu_wall_{acu_id}", self.wall_mesh, placement, orientation)


class ServerModel:
    size: dict
    is_meshed: bool

    @classmethod
    def from_dict(cls, model_data: dict):
        obj = cls()
        slot_height = 0.05
        width = 0.6
        obj.size = {
            "dx": width,
            "dy": model_data["depth"],
            "dz": model_data["occupation"] * slot_height,
        }
        obj.is_meshed = False
        return obj

    @staticmethod
    def make_sub_face(box, group, side: str):
        face = util.sub_face(box, side)
        group = util.geom.MakeCutList(group, [face], True)
        return group, face

    def mesh(self):
        box = util.make_box(self.size)
        wall = util.group_by_faces(box, exclude=["front", "rear"])
        inlet = util.sub_face(box, "front")
        outlet = util.sub_face(box, "rear")
        self.wall_mesh = util.mesh(wall, 0.1, 0.6)
        self.inlet_mesh = util.mesh(inlet, 0.1, 0.6)
        self.outlet_mesh = util.mesh(outlet, 0.1, 0.6)
        self.is_meshed = True

    def make(self, server_id, placement, orientation):
        if self.is_meshed is False:
            self.mesh()
        util.copy_mesh(
            f"server_wall_{server_id}", self.wall_mesh, placement, orientation
        )
        util.copy_mesh(
            f"server_inlet_{server_id}", self.inlet_mesh, placement, orientation
        )
        util.copy_mesh(
            f"server_outlet_{server_id}", self.outlet_mesh, placement, orientation
        )


class RackModel:
    size: dict
    first_slot_offset: float
    is_meshed: bool

    @classmethod
    def from_dict(cls, model_data: dict):
        obj = cls()
        obj.size = model_data["size"]
        obj.first_slot_offset = model_data["first_slot_offset"]
        obj.is_meshed = False
        return obj

    def mesh(self):
        box = util.make_box(self.size)
        group = util.group_by_faces(box, exclude=["front", "rear"])
        self.rack_wall_mesh = util.mesh(group, 0.1, 2)

        blanking_box = util.make_box({**self.size, "dz": 0.05})
        blanking = util.group_by_faces(
            blanking_box, exclude=["top", "bottom", "left", "right", "rear"]
        )
        self.rack_blanking_mesh = util.mesh(blanking, 0.05, 1)
        self.is_meshed = True

    def make(self, rack_id, placement, orientation):
        if self.is_meshed is False:
            self.mesh()
        util.copy_mesh(
            f"rack_wall_{rack_id}", self.rack_wall_mesh, placement, orientation
        )

    def make_blanking(self, rack_id, placement, orientation, slots: list):
        if self.is_meshed is False:
            self.mesh()

        meshes = []
        if True:
            meshes.append(
                util.copy_mesh(
                    f"rack_wall_{rack_id}_panel_default_0)",
                    self.rack_blanking_mesh,
                    {**placement, "z": 0},
                    orientation,
                    is_export=False,
                )
            )
            meshes.append(
                util.copy_mesh(
                    f"rack_wall_{rack_id}_panel_default_0)",
                    self.rack_blanking_mesh,
                    {**placement, "z": 0.05},
                    orientation,
                    is_export=False,
                )
            )
        for slot in slots:
            z = placement["z"] + self.first_slot_offset
            z += 0.05 * (slot - 1)
            mesh = util.copy_mesh(
                f"rack_wall_{rack_id}_panel_{slot}",
                self.rack_blanking_mesh,
                {**placement, "z": z},
                orientation,
                is_export=False,
            )
            meshes.append(mesh)
        compound_mesh = smesh.Concatenate(
            [mesh.GetMesh() for mesh in meshes], 1, 1, 1e-05, False
        )
        util.export_stl(compound_mesh, f"rack_wall_{rack_id}_panel")


class Builder:
    def __init__(self) -> None:
        self.partition_wall_list: list = list(
            room["constructions"]["partition_walls"].values()
        )
        self.contaiments: list = list(room["constructions"]["containments"].values())
        self.ceiling: dict = room["constructions"].get("ceiling", None)
        self.acus: dict = room["objects"]["acus"]
        self.racks: dict = room["objects"]["racks"]
        self.server_list: list = list(room["objects"]["servers"].values())

        self.acu_models: dict = room["objects"]["acu_models"]
        self.rack_models: dict = room["objects"]["rack_models"]
        self.server_models: dict = room["objects"]["server_models"]

        self.computed_rack_models: dict = dict()

        self.floor_height = 0
        self.slot_height = 0.05

        self.ceiling_face = None

    def make_acus(self):
        models = dict()
        for k, v in self.acu_models.items():
            models[k] = ACUModel.from_dict(v)
        for acu in self.acus.values():
            model = models[acu["model"]]
            model.make_acu(acu["id"], acu["placement"], acu["orientation"])

    def make_racks(self):
        for k, v in self.rack_models.items():
            self.computed_rack_models[k] = RackModel.from_dict(v)
        for rack in self.racks.values():
            model = self.computed_rack_models[rack["model"]]
            model.make(rack["id"], rack["placement"], rack["orientation"])

    def make_servers(self):
        models = dict()
        for k, v in self.server_models.items():
            models[k] = ServerModel.from_dict(v)

        rack_blanking_panels = dict()
        for server in self.server_list:
            model = models[server["model"]]
            rack = self.racks[server["rack_id"]]
            blanking_panels = rack_blanking_panels.get(
                rack["id"], list(range(1, self.rack_models[rack["model"]]["slot"] + 1))
            )
            rack_blanking_panels[rack["id"]] = [
                panel
                for panel in blanking_panels
                if panel
                not in [
                    x
                    for x in range(
                        server["slot"],
                        server["slot"]
                        + self.server_models[server["model"]]["occupation"],
                    )
                ]
            ]

            offset = self.rack_models[rack["model"]]["first_slot_offset"]
            model.make(
                server["id"],
                {
                    **rack["placement"],
                    "z": offset + self.slot_height * (server["slot"] - 1),
                },
                rack["orientation"],
            )

        for rack_id, blanking_panels in rack_blanking_panels.items():
            rack = self.racks[rack_id]
            has_blanking_panel = rack.get("has_blanking_panel", False)
            if has_blanking_panel:
                if len(self.computed_rack_models) == 0:
                    for k, v in self.rack_models.items():
                        self.computed_rack_models[k] = RackModel.from_dict(v)
                rack_model: RackModel = self.computed_rack_models[rack["model"]]
                rack_model.make_blanking(
                    rack["id"],
                    rack["placement"],
                    rack["orientation"],
                    slots=blanking_panels,
                )

    def make_partition_wall_list(self):
        for i, wall in enumerate(self.partition_wall_list):
            placement, size = wall["placement"], wall["size"]
            basic_face = util.geom.MakeFaceHW(size["dz"], size["dx"], 3)
            for vent_opening in wall["vent_opening_list"]:
                vent_face = util.geom.MakeFaceHW(
                    vent_opening["length"], vent_opening["width"], 3
                )
                vent_face = util.geom.MakeTranslation(
                    vent_face,
                    (
                        vent_opening["offset_h"]
                        - (size["dx"] - vent_opening["length"]) / 2
                    ),
                    0,
                    (
                        vent_opening["offset_v"]
                        - (size["dz"] - vent_opening["width"]) / 2
                    ),
                )
                basic_face = util.geom.MakeCut(basic_face, vent_face)
            vector = util.geom.MakeVectorDXDYDZ(0, 1, 0)
            _box = util.geom.MakePrismVecH(basic_face, vector, size["dy"])
            box = util.move_placement(
                _box,
                {
                    "x": placement["x"] + size["dx"] / 2,
                    "y": placement["y"],
                    "z": (size["dz"] - placement["z"]) / 2,
                },
            )

            group = util.group_by_faces(box)
            mesh_obj = util.mesh(group, 1, 4)
            util.export_stl(mesh_obj, f"partition_wall_{i}")

    def make_room(self):
        oz = geompy.MakeVectorDXDYDZ(0, 0, 1)
        vertices = []
        for vertex in room["plane_outline"]:
            vertices.append(geompy.MakeVertex(vertex["x"], vertex["y"], vertex["z"]))
        lines = []
        for i in range(len(vertices)):
            start, end = i, i + 1 if i < len(vertices) - 1 else 0
            lines.append(geompy.MakeLineTwoPnt(vertices[start], vertices[end]))
        face = geompy.MakeFaceWires(lines, 1)
        prism = geompy.MakePrismVecH(face, oz, room["height"])
        box_faces = util.group_by_faces(prism)
        util.export_stl(util.mesh(box_faces, 2, 6), "room_wall_1")

        # Make ceiling
        if self.ceiling is not None:
            self.ceiling_face = util.move_placement(
                face, {"x": 0, "y": 0, "z": self.ceiling["height"]}
            )

    def make_containments(self):
        for index, contaiment in enumerate(self.contaiments):
            box = util.make_box(contaiment["size"], contaiment["placement"])
            exclude_faces = []
            for face in list(SalomeUtil.SUB_FACE_SIZE_INDICES):
                if not contaiment[face]:
                    exclude_faces.append(face)
            contaiment_box = util.group_by_faces(box, exclude=exclude_faces)
            util.export_stl(util.mesh(contaiment_box, 0.5, 2), f"containment_{index}")

    def make_ceiling(self):
        duct_faces = []

        # duct out
        duct_list = self.ceiling["duct_list"]
        for index, duct in enumerate(duct_list):
            box = util.make_box(duct["size"], duct["placement"])
            duct_box = util.group_by_faces(box, exclude=["top", "bottom"])
            util.export_stl(util.mesh(duct_box, 0.5, 2), f"ceiling_duct_{index}")
            duct_faces.append(util.sub_face(box, "top"))

        self.ceiling_face = util.geom.MakeCutList(self.ceiling_face, duct_faces)
        util.export_stl(util.mesh(self.ceiling_face, 0.5, 5), "ceiling_1")

    def run(self, runner_id, runner_count):
        if runner_id is None or runner_count is None:
            self.make_room()
            if self.ceiling is not None:
                self.make_ceiling()
            self.make_containments()
            self.make_partition_wall_list()
            self.make_acus()
            self.make_racks()
            self.make_servers()
        else:
            runner_id = int(runner_id)
            runner_count = int(runner_count)
            if runner_id == 0:
                self.make_room()
                if self.ceiling is not None:
                    self.make_ceiling()
                self.make_partition_wall_list()
                self.make_acus()
                self.make_racks()
            else:
                server_num = int(len(self.server_list) / runner_count)
                start = (runner_id - 1) * server_num
                end = (
                    len(self.server_list)
                    if runner_id == runner_count
                    else runner_id * server_num
                )
                self.server_list = self.server_list[start:end]
                self.make_servers()


def main():
    runner_id = os.getenv("RUNNER_ID")
    runner_count = os.getenv("RUNNER_COUNT")
    Builder().run(runner_id, runner_count)
    if SAVE_HDF:
        salome.myStudy.SaveAs("output.hdf", False, False)


main()
