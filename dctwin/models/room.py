import json
from pathlib import Path
from typing import List, Optional, OrderedDict, Union, Tuple

from dctwin.models.basics import Face, Size, Vertex
from dctwin.models.geometry_utils import rotate
from dctwin.models.geometry_model import RoomGeometryModel, ACUModel, ACUFace, RackModel, ServerModel, BoxModel, BoxFaces
from pydantic import BaseModel, Field, root_validator
from dctwin.models.geometry_utils import convert_json_file


class Opening(BaseModel):
    location: Vertex
    size: Size
    velocity: Optional[Size] = None


# 1111
class VentOpening(BaseModel):
    width: float
    length: float
    offset_h: float
    offset_v: float


class PartitionWall(BaseModel):
    id: str
    size: Size
    placement: Vertex
    vent_opening_list: List[VentOpening] = Field(default_factory=list)


class Containment(BaseModel):
    size: Size
    placement: Vertex
    front: bool = True
    rear: bool = True
    left: bool = True
    right: bool = True
    top: bool = True
    bottom: bool = True


class Pillar(BaseModel):
    id: str
    size: Size
    placement: Vertex


class Duct(BaseModel):
    placement: Vertex


# 111111
class SecondaryCeilingOrFloorGeometry(BaseModel):
    height: float
    openings: OrderedDict[str, Opening] = Field(default_factory=dict)


class SecondaryCeilingOrFloor(BaseModel):
    geometry: SecondaryCeilingOrFloorGeometry


class BoxGeometry(BoxModel):
    model: str
    size: Size
    location: Vertex
    faces: Optional[BoxFaces] = None


class Box(BaseModel):
    geometry: BoxGeometry


class ACUGeometry(ACUModel):
    model: str = ""
    orientation: int
    location: Vertex

    size: Optional[Size] = None
    supply_face: Optional[ACUFace] = None
    return_face: Optional[ACUFace] = None

    min_temperature: Optional[float] = None
    flow_rate: Optional[float] = None
    cooling_capacity: Optional[float] = None

    def calculate_face_area(self, face: Face) -> float:
        if face in (Face.front, Face.rear):
            return self.size.x / 2 * self.size.z / 2
        if face in (Face.left, Face.right):
            return self.size.x / 2 * self.size.z / 2
        if face in (Face.bottom, Face.top):
            return self.size.x / 2 * self.size.z / 2
        raise ValueError(f"No such face: {face}")

    @property
    def supply_area(self):
        return self.calculate_face_area(self.supply_face.side)

    @property
    def return_area(self):
        return self.calculate_face_area(self.return_face.side)

    @property
    def k(self) -> float:
        """turbulent kinetic energy
        Others:
        omega = epsilon / (0.09 * k)
        """
        tu = 0.1
        u = float(self.flow_rate / self.supply_area)
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        """
        turbulent dissipation rate
        """
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)


class ACU(BaseModel):
    geometry: ACUGeometry


class ServerGeometry(ServerModel):
    """
    depth: server depth
    occupation: How many slots the server will occupy
    rated_power: unit(W)
    extend_to_rack_width: extend the server width to equal the rack width or not
    """

    model: str
    slot_position: int

    orientation: Optional[int] = None
    depth: Optional[float] = None
    slot_occupation: Optional[int] = None
    width: Optional[float] = None
    heat_load: Optional[float] = None
    flow_rate: Optional[float] = None

    @property
    def height(self) -> float:
        return self.slot_occupation * 0.045

    @property
    def inlet_area(self) -> float:
        if self.orientation == 90:
            return -self.height * float(self.width)
        else:
            return self.height * float(self.width)

    @property
    def outlet_area(self) -> float:
        if self.orientation == 90:
            return -self.height * float(self.width)
        else:
            return self.height * float(self.width)

    @property
    def k(self) -> float:
        tu = 0.1
        u = float(self.flow_rate) / self.outlet_area
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)


class Server(BaseModel):
    geometry: ServerGeometry


class RackGeometry(RackModel):
    model: str
    location: Vertex
    orientation: int
    has_blanking_panel: bool

    size: Optional[Size] = None
    slot: Optional[int] = None
    first_slot_offset: Optional[float] = None


class RackConstruction(BaseModel):
    servers: OrderedDict[str, Server]


class Rack(BaseModel):
    geometry: RackGeometry
    constructions: RackConstruction


class SensorGeometry(BaseModel):
    location: Vertex


class Sensor(BaseModel):
    geometry: SensorGeometry


# noinspection PyMethodParameters
class RoomConstructions(BaseModel):
    raised_floor: Optional[SecondaryCeilingOrFloor]
    false_ceiling: Optional[SecondaryCeilingOrFloor]
    boxes: Optional[OrderedDict[str, Box]]
    acus: OrderedDict[str, ACU]
    racks: OrderedDict[str, Rack]
    sensors: OrderedDict[str, Sensor]


class RoomGeometry(BaseModel):
    height: float
    plane: List[Vertex]


class ACUInputs(BaseModel):
    flow_rate: float
    min_temperature: float


class ServerInputs(BaseModel):
    flow_rate: float
    heat_load: float


class Inputs(BaseModel):
    acus: OrderedDict[str, ACUInputs]
    servers: OrderedDict[str, ServerInputs]


# noinspection PyMethodParameters
class Room(BaseModel):
    name: str
    geometry_model: RoomGeometryModel
    geometry: RoomGeometry
    constructions: RoomConstructions
    inputs: Inputs

    @classmethod
    def _validate_id(cls, v: dict):
        for _id, obj in v.items():
            if not _id.isidentifier():
                raise ValueError(f"must be valid identifier: {_id}")
        return v

    @classmethod
    def _concat_model_attributes(cls, v: dict, models):
        for _id, obj in v.items():
            model_name = obj["geometry"]["model"]
            if models.get(model_name) is not None:
                obj["geometry"] = {**obj["geometry"], **models.get(model_name)}
            else:
                raise ValueError(f"model name does not exists: {_id}")
        return v

    @classmethod
    def _concat_acu_model_attributes(cls, acus: dict, models, acu_inputs: dict):
        for _id, obj in acus.items():
            model_name = obj["geometry"]["model"]
            if _id not in acu_inputs:
                raise ValueError(f"missing input for acu {_id}")
            acu_input = {
                "flow_rate": acu_inputs[_id]["flow_rate"],
                "min_temperature": acu_inputs[_id]["min_temperature"],
                "cooling_capacity": acu_inputs[_id]["cooling_capacity"]
            }

            if models.get(model_name) is not None:
                obj["geometry"] = {
                    **obj["geometry"],
                    **models.get(model_name),
                    **acu_input
                }
            else:
                raise ValueError(f"model name does not exists: {_id}")
        return acus

    @classmethod
    def _validate_rack_and_server_id(cls, v: dict):
        for _id, obj in v.items():
            if not _id.isidentifier():
                raise ValueError(f"must be valid identifier: {_id}")
            servers = obj["constructions"]["servers"]
            for _server_id, server_obj in servers.items():
                if not _server_id.isidentifier():
                    raise ValueError(f"must be valid identifier: {_id}")
        return v

    @classmethod
    def _concat_rack_and_server_model_attributes(cls, v: dict, rack_models, server_models, server_inputs):
        for _rack_id, rack_obj in v.items():
            model_name = rack_obj["geometry"]["model"]
            if rack_models.get(model_name) is not None:
                rack_obj["geometry"] = {**rack_obj["geometry"], **rack_models.get(model_name)}
            else:
                raise ValueError(f"model name does not exists: {_rack_id}")
            servers = rack_obj["constructions"]["servers"]
            occupied_rack_slot = {}
            for _server_id, server_obj in servers.items():
                model_name = server_obj["geometry"]["model"]
                if _server_id not in server_inputs:
                    raise ValueError(f"missing input for server {_server_id}")
                server_input = {
                    "flow_rate": server_inputs[_server_id]["flow_rate"],
                    "heat_load": server_inputs[_server_id]["heat_load"]
                }
                if server_models.get(model_name) is not None:
                    server_obj["geometry"] = {
                        **server_obj["geometry"],
                        **server_models.get(model_name),
                        **server_input
                    }
                else:
                    raise ValueError(f"model name does not exists: {_rack_id}")
                if server_obj["geometry"]["slot_position"] < 1 or server_obj["geometry"]["slot_position"] + \
                        server_obj["geometry"][
                            "slot_occupation"] > rack_obj["geometry"]["slot"] + 1:
                    raise ValueError(
                        f"invalid server slot/occupation: "
                        f"Server({_server_id}, slot={server_obj['geometry']['slot_position']}, "
                        f"occupation={server_obj['geometry']['slot_occupation']})"
                    )

                for i in range(server_obj["geometry"]["slot_position"],
                               server_obj["geometry"]["slot_position"] + server_obj["geometry"][
                                   "slot_occupation"]):
                    if i not in occupied_rack_slot:
                        occupied_rack_slot[i] = _server_id
                    else:
                        raise ValueError(
                            f"invalid server slot/occupation: "
                            f"Server({_server_id}) has collision with "
                            f"Server({occupied_rack_slot[i]})"
                        )

        return v

    @root_validator(pre=True)
    def validate(cls, values):
        constructions = values["constructions"]
        geometry_model = values["geometry_model"]
        boxes = constructions["boxes"]
        acus = constructions["acus"]
        racks = constructions["racks"]
        sensors = constructions["sensors"]
        inputs = values["inputs"]

        cls._validate_id(boxes)
        cls._concat_model_attributes(boxes, geometry_model["boxes"])
        cls._validate_id(acus)
        cls._concat_acu_model_attributes(acus, geometry_model["acus"], inputs["acus"])
        cls._validate_rack_and_server_id(racks)
        cls._concat_rack_and_server_model_attributes(racks, geometry_model["racks"], geometry_model["servers"],
                                                     inputs["servers"])
        cls._validate_id(sensors)

        return values

    def server_patch_positions(self, server_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of server inlet and outlet"""

        for rack_id, rack in self.constructions.racks.items():
            if server_id in rack.constructions.servers:
                server = rack.constructions.servers.get(server_id)
                server_rack = rack

        rack: Rack = server_rack
        # rack_model = self.objects.rack_models[rack.model]
        # server_model = self.objects.server_models[server.model]

        z = rack.geometry.location.z + rack.geometry.first_slot_offset + 0.045 * (
                server.geometry.slot_position - 1)
        z = round(z, 3)

        # inlet
        inlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
        inlet_y = rack.geometry.location.y

        inlet_x, inlet_y = rotate(
            (rack.geometry.location.x, rack.geometry.location.y), (inlet_x, inlet_y), rack.geometry.orientation
        )
        inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

        # outlet
        outlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
        outlet_y = rack.geometry.location.y + server.geometry.depth
        outlet_x, outlet_y = rotate(
            (rack.geometry.location.x, rack.geometry.location.y), (outlet_x, outlet_y), rack.geometry.orientation
        )
        outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y, 3), z=z)
        return inlet, outlet

    def acu_patch_positions(self, acu_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of acu return and supply"""
        acu: ACU = self.constructions.acus.get(acu_id)

        def get_raw_point(face):
            if face.side == Face.front:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.rear:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.left:
                x = acu.geometry.location.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.right:
                x = acu.geometry.location.x + acu.geometry.size.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.top:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = acu.geometry.size.z
            elif face.side == Face.bottom:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = 0
            else:
                raise ValueError(f"not supported: face.side={face.side}")
            if self.constructions.raised_floor is not None:
                z += self.constructions.raised_floor.geometry.height
            return round(x, 3), round(y, 3), round(z, 3)

        def get_center_coordinate(face):
            x, y, z = get_raw_point(face)
            x, y = rotate(
                (acu.geometry.location.x, acu.geometry.location.y), (x, y), acu.geometry.orientation
            )
            return Vertex(x=round(x, 3), y=round(y, 3), z=z)

        inlet = get_center_coordinate(acu.geometry.return_face)
        outlet = get_center_coordinate(acu.geometry.supply_face)

        return inlet, outlet

    @property
    def probes(self):
        return list(self.constructions.sensors.values())

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2))

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "Room":
        with open(file_path) as f:
            return cls(**convert_json_file(json.load(f)))
