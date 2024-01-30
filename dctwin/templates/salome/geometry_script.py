# pylava:skip=1
import json
import logging

import math
import os
from pathlib import Path
from typing import Dict, List

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
except Exception:
    raise ImportError("salome not found")

# Init
SRC_PATH = Path(os.getcwd(), "scripts/room.json")
if os.getenv("SRC_PATH"):
    SRC_PATH = os.getenv("SRC_PATH")
logging.info(f"source path {SRC_PATH}")
OUTPUT_PATH = Path(os.getcwd(), "output")
if os.getenv("OUTPUT_PATH"):
    OUTPUT_PATH = os.getenv("OUTPUT_PATH")
logging.info(f"output path {OUTPUT_PATH}")
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

    def __init__(self, skip_pre_mesh=False) -> None:
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
        box = self.geom.MakeBoxDXDYDZ(size["x"], size["y"], size["z"])
        if placement is not None:
            return self.move_placement(box, placement)
        return box

    def generate_stl(self, box, group_id: str) -> None:
        group = self.geom.CreateGroup(box, self.geom.ShapeType["FACE"])
        self.geom.UnionIDs(
            group, self.geom.SubShapeAllIDs(box, self.geom.ShapeType["FACE"])
        )
        self.geom.addToStudy(group, group_id)

        file_stl = Path(OUTPUT_PATH, f"{group_id}.stl")
        self.geom.ExportSTL(group, str(file_stl), False)

    def sub_face_ids(self, geom_obj):
        return self.geom.SubShapeAllIDs(geom_obj, self.geom.ShapeType["FACE"])

    def group_by_faces(self, geom_obj, exclude: List = None):
        group = self.geom.CreateGroup(geom_obj, self.geom.ShapeType["FACE"])
        face_ids = self.sub_face_ids(geom_obj)
        if exclude is not None:
            exclude_indices = [self.SUB_FACE_INDICES[i] for i in exclude]
            face_ids = [
                face_ids[i] for i, _ in enumerate(face_ids) if i not in exclude_indices
            ]
        self.geom.UnionIDs(group, face_ids)
        return group

    def sub_faces(self, geom_obj, exclude: List = None):
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

    def copy_mesh(
        self,
        name: str,
        mesh_obj,
        placement: Dict,
        orientation: float = 0,
        is_export: bool = True,
    ):
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

    def export_stl(self, mesh, name: str):
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
    is_meshed: bool = False

    @classmethod
    def from_dict(cls, acu_model_data: Dict) -> "ACUModel":
        obj = cls()
        obj.size = acu_model_data["size"]
        obj.supply_data = acu_model_data["supply_face"]
        obj.return_data = acu_model_data["return_face"]
        return obj

    @staticmethod
    def make_sub_face(box, group, data: Dict):
        face = util.sub_face(box, data["side"])
        if data["side"] in ("top", "bottom"):
            face = util.geom.MakeFaceObjHW(face, data["width"], data["length"])
        else:
            face = util.geom.MakeFaceObjHW(face, data["length"], data["width"])
        face = util.move_placement(face, data["offset"])
        group = util.geom.MakeCutList(group, [face], True)
        return group, face

    def mesh(self) -> None:
        box = util.make_box(self.size)
        group = util.group_by_faces(box)

        group, supply_face = self.make_sub_face(box, group, self.supply_data)
        group, return_face = self.make_sub_face(box, group, self.return_data)
        self.supply_mesh = util.mesh(supply_face, 0.1, 5)
        self.return_mesh = util.mesh(return_face, 0.1, 5)
        self.wall_mesh = util.mesh(group, 0.1, 5)
        self.is_meshed = True

    def make_acu(self, acu_id: str, placement: Dict, orientation: float) -> None:
        if self.is_meshed is False:
            self.mesh()
        util.copy_mesh(f"acu_supply_{acu_id}", self.supply_mesh, placement, orientation)
        util.copy_mesh(f"acu_return_{acu_id}", self.return_mesh, placement, orientation)
        util.copy_mesh(f"acu_wall_{acu_id}", self.wall_mesh, placement, orientation)


class ServerModel:
    size: dict
    is_meshed: bool
    inlet_face: Dict
    outlet_face: Dict

    @classmethod
    def from_dict(cls, model_data: dict) -> "ServerModel":
        obj = cls()
        slot_height = 0.045
        obj.size = {
            "x": model_data["width"],
            "y": model_data["depth"],
            "z": model_data["slot_occupation"] * slot_height,
        }
        obj.is_meshed = False
        obj.inlet_face = model_data["inlet_face"]
        obj.outlet_face = model_data["outlet_face"]
        return obj

    @staticmethod
    def make_sub_face(box, group, data: Dict):
        face = util.sub_face(box, data["side"])
        face = util.geom.MakeFaceObjHW(face, data["length"], data["width"])
        face = util.move_placement(face, data["offset"])
        group = util.geom.MakeCutList(group, [face], True)
        return group, face

    def mesh(self) -> None:
        box = util.make_box(self.size)
        wall = util.group_by_faces(box)
        if self.inlet_face is None:
            inlet_face = util.sub_face(box, "front")
        else:
            wall, inlet_face = self.make_sub_face(box, wall, self.inlet_face)
        if self.outlet_face is None:
            outlet_face = util.sub_face(box, "rear")
        else:
            wall, outlet_face = self.make_sub_face(box, wall, self.outlet_face)
        self.wall_mesh = util.mesh(wall, 0.1, 0.6)
        self.inlet_mesh = util.mesh(inlet_face, 0.1, 0.6)
        self.outlet_mesh = util.mesh(outlet_face, 0.1, 0.6)
        self.is_meshed = True

    def make(self, server_id: str, placement: Dict, orientation: float) -> None:
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
    excluded_faces: List[str] = [
        "front",
        "rear",
    ]  # default exclude front and rear for rack

    slot_height = 0.045  # 1U = 0.045 mm

    @classmethod
    def from_dict(cls, model_data: Dict) -> "RackModel":
        obj = cls()
        obj.size = model_data["size"]
        obj.first_slot_offset = model_data["first_slot_offset"]
        obj.is_meshed = False
        for face in list(SalomeUtil.SUB_FACE_SIZE_INDICES):
            if model_data["faces"] is not None:
                if not model_data["faces"][face] and face not in obj.excluded_faces:
                    obj.excluded_faces.append(face)
        return obj

    def mesh(self) -> None:
        box = util.make_box(self.size)
        group = util.group_by_faces(box, exclude=self.excluded_faces)
        self.rack_wall_mesh = util.mesh(group, 0.1, 2)
        blanking_box = util.make_box({**self.size, "z": 0.044, "y": 0.1})
        blanking_box = util.group_by_faces(
            blanking_box, exclude=["rear", "bottom", "top", "left", "right"]
        )  # Remain only front face
        self.rack_blanking_mesh = util.mesh(blanking_box, 0.05, 1)
        self.is_meshed = True

    def make(self, rack_id: str, placement: Dict, orientation: float) -> None:
        if self.is_meshed is False:
            self.mesh()
        util.copy_mesh(
            f"rack_wall_{rack_id}", self.rack_wall_mesh, placement, orientation
        )

    def make_blanking(
        self, rack_id: str, placement: Dict, orientation: float, slots: list
    ) -> None:
        if self.is_meshed is False:
            self.mesh()

        meshes = []
        if not self.first_slot_offset:
            try:
                slots.remove(1)
            except ValueError:
                pass
        for slot in slots:
            z = placement["z"]
            z += self.slot_height * (slot - 1)
            z += self.first_slot_offset
            mesh = util.copy_mesh(
                f"rack_panel_{rack_id}_{slot}",
                self.rack_blanking_mesh,
                {**placement, "z": z},
                orientation,
                is_export=False,
            )
            meshes.append(mesh)
        compound_mesh = smesh.Concatenate(
            [mesh.GetMesh() for mesh in meshes], 1, 1, 1e-05, False
        )
        util.export_stl(compound_mesh, f"rack_panel_{rack_id}")


class Builder:

    slot_height = 0.045  # 1U = 0.045 mm

    @staticmethod
    def make_acus(acus: Dict, acu_geometry_models: Dict) -> None:
        acu_models = dict()
        for acu_model_key, acu_model_value in acu_geometry_models.items():
            acu_models[acu_model_key] = ACUModel.from_dict(acu_model_value)
        for acu_key, acu in acus.items():
            try:
                acu_model = acu_models[acu["geometry"]["model"]]
            except KeyError:
                logging.warning(f"ACU model {acu['geometry']['model']} not found")
                acu_model = ACUModel.from_dict(acu["geometry"])
            acu_model.make_acu(
                acu_key, acu["geometry"]["location"], acu["geometry"]["orientation"]
            )

    @staticmethod
    def make_boxes(boxes: Dict) -> None:
        boxes_types_index = {}
        for box in boxes.values():
            if box["geometry"]["model"] not in boxes_types_index:
                boxes_types_index[box["geometry"]["model"]] = 1
            else:
                boxes_types_index[box["geometry"]["model"]] += 1
            if box["geometry"].get("openings", None) is not None:
                size = box["geometry"]["size"]
                location = box["geometry"]["location"]
                if (
                    box["geometry"]["openings_side"] == "front"
                    or box["geometry"]["openings_side"] == "rear"
                ):
                    basic_face_input = [size["z"], size["x"], 3]
                elif (
                    box["geometry"]["openings_side"] == "left"
                    or box["geometry"]["openings_side"] == "right"
                ):
                    basic_face_input = [size["z"], size["y"], 2]
                elif (
                    box["geometry"]["openings_side"] == "top"
                    or box["geometry"]["openings_side"] == "bottom"
                ):
                    basic_face_input = [size["x"], size["y"], 1]
                else:
                    raise ValueError(
                        f"Unknown openings_side: {box['geometry']['openings_side']}"
                    )
                basic_face = util.geom.MakeFaceHW(*basic_face_input)
                box_vector_and_distance_input = []
                move_box_input = {}
                for key, opening in box["geometry"]["openings"].items():
                    if (
                        box["geometry"]["openings_side"] == "front"
                        or box["geometry"]["openings_side"] == "rear"
                    ):
                        vent_face_input = [
                            opening["size"]["x"],
                            opening["size"]["z"],
                            3,
                        ]
                        vent_face_translation_input = [
                            (
                                opening["location"]["x"]
                                - (size["x"] - opening["size"]["x"]) / 2
                            ),
                            0,
                            (
                                opening["location"]["z"]
                                - (size["z"] - opening["size"]["z"]) / 2
                            ),
                        ]
                        vector_input = [0, 1, 0]
                        vector = util.geom.MakeVectorDXDYDZ(*vector_input)
                        box_vector_and_distance_input = [vector, size["y"]]
                        move_box_input = {
                            "x": location["x"] + size["x"] / 2,
                            "y": location["y"],
                            "z": (size["z"] / 2) + location["z"],
                        }
                    elif (
                        box["geometry"]["openings_side"] == "left"
                        or box["geometry"]["openings_side"] == "right"
                    ):
                        vent_face_input = [
                            opening["size"]["y"],
                            opening["size"]["z"],
                            2,
                        ]
                        vent_face_translation_input = [
                            0,
                            (
                                opening["location"]["y"]
                                - (size["y"] - opening["size"]["y"]) / 2
                            ),
                            (
                                opening["location"]["z"]
                                - (size["z"] - opening["size"]["z"]) / 2
                            ),
                        ]
                        vector_input = [1, 0, 0]
                        vector = util.geom.MakeVectorDXDYDZ(*vector_input)
                        box_vector_and_distance_input = [vector, size["x"]]
                        move_box_input = {
                            "x": location["x"],
                            "y": location["y"] + size["y"] / 2,
                            "z": (size["z"] / 2) + location["z"],
                        }
                    elif (
                        box["geometry"]["openings_side"] == "top"
                        or box["geometry"]["openings_side"] == "bottom"
                    ):
                        vent_face_input = [
                            opening["size"]["x"],
                            opening["size"]["y"],
                            1,
                        ]
                        vent_face_translation_input = [
                            (
                                opening["location"]["x"]
                                - (size["x"] - opening["size"]["x"]) / 2
                            ),
                            (
                                opening["location"]["y"]
                                - (size["y"] - opening["size"]["y"]) / 2
                            ),
                            0,
                        ]
                        vector_input = [0, 0, 1]
                        vector = util.geom.MakeVectorDXDYDZ(*vector_input)
                        box_vector_and_distance_input = [vector, size["z"]]
                        move_box_input = {
                            "x": location["x"] + size["x"] / 2,
                            "y": location["y"] + (size["y"] / 2),
                            "z": location["z"],
                        }
                    else:
                        raise ValueError(
                            f"Unknown openings_side: {box['geometry']['openings_side']}"
                        )
                    vent_face = util.geom.MakeFaceHW(*vent_face_input)
                    vent_face = util.geom.MakeTranslation(
                        vent_face, *vent_face_translation_input
                    )
                    basic_face = util.geom.MakeCut(basic_face, vent_face)
                _box = util.geom.MakePrismVecH(
                    basic_face, *box_vector_and_distance_input
                )
                geometry_box = util.move_placement(
                    _box,
                    move_box_input,
                )
                group = util.group_by_faces(geometry_box)
                mesh_obj = util.mesh(group, 1, 4)
                util.export_stl(
                    mesh_obj,
                    f"box_{box['geometry']['model']}_{boxes_types_index[box['geometry']['model']]}",
                )

            else:
                geometry_box = util.make_box(
                    box["geometry"]["size"], box["geometry"]["location"]
                )
                exclude_faces = []
                for face in list(SalomeUtil.SUB_FACE_SIZE_INDICES):
                    if not box["geometry"]["faces"][face]:
                        exclude_faces.append(face)
                group = util.group_by_faces(geometry_box, exclude=exclude_faces)
                util.export_stl(
                    util.mesh(group, 0.5, 2),
                    f"box_{box['geometry']['model']}_{boxes_types_index[box['geometry']['model']]}",
                )

    def make_racks(
        self, racks: Dict, rack_geometry_models: Dict, server_geometry_models: Dict
    ) -> None:
        rack_models, server_models = dict(), dict()
        for rack_model_key, rack_model_value in rack_geometry_models.items():
            rack_models[rack_model_key] = RackModel.from_dict(rack_model_value)
        for server_model_key, server_model_value in server_geometry_models.items():
            server_models[server_model_key] = ServerModel.from_dict(server_model_value)
        for rack_key, rack in racks.items():
            try:
                rack_model = rack_models[rack["geometry"]["model"]]
            except KeyError:
                logging.critical(f"Rack model {rack['geometry']['model']} not found")
                exit(1)
            rack_model.make(
                rack_id=rack_key,
                placement=rack["geometry"]["location"],
                orientation=rack["geometry"]["orientation"],
            )
            available_slots = self.make_servers(
                rack_key, rack, rack_model, server_models
            )
            if rack["geometry"]["has_blanking_panel"]:
                blanking_panels = []
                for slot, is_available in available_slots.items():
                    if is_available:
                        blanking_panels.append(slot)
                rack_model.make_blanking(
                    rack_key,
                    rack["geometry"]["location"],
                    rack["geometry"]["orientation"],
                    slots=blanking_panels,
                )

    def make_servers(
        self, rack_key: str, rack: Dict, rack_model: RackModel, server_models: Dict
    ) -> Dict:
        available_slots = {}
        for slot in range(1, rack["geometry"]["slot"] + 1):
            available_slots[slot] = True

        for server_key, server in rack["constructions"]["servers"].items():
            try:
                server_model = server_models[server["geometry"]["model"]]
            except KeyError:
                logging.warning(f"Server model {rack['geometry']['model']} not found")
                server_model = ServerModel.from_dict(server["geometry"])
            server_starting_slot = server["geometry"]["slot_position"]
            server_ending_slot = (
                server["geometry"]["slot_position"]
                + server["geometry"]["slot_occupation"]
            )
            for server_slot in range(server_starting_slot, server_ending_slot):
                available_slots[server_slot] = False

            server_height = (
                rack["geometry"]["location"]["z"]
                + rack["geometry"]["first_slot_offset"]
                + self.slot_height * (server_starting_slot - 1)
            )
            server_model.make(
                server_key,
                {**rack["geometry"]["location"], "z": server_height},
                rack["geometry"]["orientation"],
            )

        return available_slots

    @staticmethod
    def make_panels(base_face, plane: Dict, name: str) -> None:
        floor_face = util.move_placement(
            base_face, {"x": 0, "y": 0, "z": plane["geometry"]["height"]}
        )
        opening_faces = []
        opening_list = plane["geometry"]["openings"].values()
        for opening in opening_list:
            # Just for cutting face
            opening["size"]["z"] = 0.1
            opening["location"]["z"] = plane["geometry"]["height"]
            box = util.make_box(opening["size"], opening["location"])
            opening_faces.append(util.sub_face(box, "bottom"))
        floor_face = util.geom.MakeCutList(floor_face, opening_faces)
        util.export_stl(util.mesh(floor_face, 0.5, 5), f"{name}")

    def make_room(self, geometry_models: Dict) -> None:
        oz = geompy.MakeVectorDXDYDZ(0, 0, 1)
        vertices = []
        for vertex in room["geometry"]["plane"]:
            vertices.append(geompy.MakeVertex(vertex["x"], vertex["y"], vertex["z"]))
        lines = []
        for i in range(len(vertices)):
            start, end = i, i + 1 if i < len(vertices) - 1 else 0
            lines.append(geompy.MakeLineTwoPnt(vertices[start], vertices[end]))
        face = geompy.MakeFaceWires(lines, 1)
        prism = geompy.MakePrismVecH(face, oz, room["geometry"]["height"])
        # Setup raised floor
        box = util.move_placement(prism, {"x": 0, "y": 0, "z": 0})
        box_faces = util.group_by_faces(box)
        util.export_stl(util.mesh(box_faces, 2, 6), f"room_wall_1")
        # Make objects in the room (e.g., ceiling, raised floor, rack, etc.)
        raised_floor = room["constructions"].get("raised_floor", None)
        false_ceiling = room["constructions"].get("false_ceiling", None)
        boxes = room["constructions"].get("boxes", None)
        acus = room["constructions"].get("acus", None)
        racks = room["constructions"].get("racks", None)
        self.make_panels(
            base_face=face, plane=raised_floor, name="floor_1"
        ) if raised_floor else None
        self.make_panels(
            base_face=face, plane=false_ceiling, name="ceiling_1"
        ) if false_ceiling else None
        self.make_boxes(boxes=boxes) if boxes else None
        self.make_acus(
            acus=acus,
            acu_geometry_models=geometry_models["acus"],
        ) if acus else None
        self.make_racks(
            racks=racks,
            rack_geometry_models=geometry_models["racks"],
            server_geometry_models=geometry_models["servers"],
        ) if racks else None

    def run(self) -> None:
        geometry_models = room["models"]["geometry_models"]
        self.make_room(geometry_models)


def main():
    Builder().run()
    if SAVE_HDF:
        salome.myStudy.SaveAs("output.hdf", False, False)


main()
