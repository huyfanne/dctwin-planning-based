"""Implemented objects for data hall
"""
import json
from pathlib import Path
from typing import Union, Tuple, ForwardRef
from pydantic import root_validator, BaseModel
from loguru import logger

from .basics import Face, Vertex
from .geometry import (
    PlaneGeometry,
    BoxGeometry,
    ACUGeometry,
    RackGeometry,
    RoomGeometry,
    ServerGeometry,
    SensorGeometry,
    RoomGeometryModel,
)
from .inputs import Inputs
from .utils import convert_json_file, rotate


class Plane(BaseModel):
    geometry: PlaneGeometry


class Box(BaseModel):
    geometry: BoxGeometry


class RaisedFloor(Plane):
    pass


class ACU(BaseModel):
    geometry: ACUGeometry


class Server(BaseModel):
    geometry: ServerGeometry


class Sensor(BaseModel):
    geometry: SensorGeometry
    meta: dict


class Rack(BaseModel):
    geometry: RackGeometry
    constructions: ForwardRef('RackConstruction')


class Room(BaseModel):
    name: str
    geometry_model: RoomGeometryModel
    geometry: RoomGeometry
    constructions: ForwardRef("RoomConstructions")
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

                for i in range(int(server_obj["geometry"]["slot_position"]),
                               int(server_obj["geometry"]["slot_position"] + server_obj["geometry"][
                                   "slot_occupation"])):
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

        logger.critical(f"server {server_id} not found")
        exit(-1)

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


from .constructions import RackConstruction, RoomConstructions
Rack.update_forward_refs()
Room.update_forward_refs()
