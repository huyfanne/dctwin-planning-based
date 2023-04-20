"""
Building is the highest level object in a data center.
It contains all the data halls (rooms) and the built-in facilities.
"""
import json
from pathlib import Path
from typing import Union, Optional, Dict, OrderedDict, List
from pydantic import BaseModel, validator
from .basics import Vertex
from .room import Room, RoomConstruction
from .acu import ACU
from .box import Box
from .server import Server
from .rack import RackConstruction, Rack
from .utils import convert_json_file
from .models import Model


class BuildingGeometry(BaseModel):
    """ Building geometry is used to define the geometry of the building """
    height: Optional[float]
    plane: Optional[List[Vertex]]


class BuildingConstruction(BaseModel):
    """ Building construction is used to define the data halls in a building """
    rooms: OrderedDict[str, Room]


class Building(BaseModel):
    """ Building object: the highest level object in a data center
    """
    meta: Optional[OrderedDict]
    geometry: Optional[BuildingGeometry]
    models: Optional[Model]
    constructions: BuildingConstruction

    @classmethod
    def _validate_id(cls, _id: str):
        if not _id.isidentifier():
            raise ValueError(f"must be valid identifier: {_id}")

    @classmethod
    def _validate_geometry_models(cls, obj, models: Dict):
        model_name = obj.geometry.model
        if isinstance(obj, ACU):
            obj.geometry.size = models.get(model_name).size
            obj.geometry.supply_face = models.get(model_name).supply_face
            obj.geometry.return_face = models.get(model_name).return_face
        elif isinstance(obj, Rack):
            obj.geometry.size = models.get(model_name).size
            obj.geometry.slot = models.get(model_name).slot
            obj.geometry.first_slot_offset = models.get(model_name).first_slot_offset
        elif isinstance(obj, Server):
            obj.geometry.slot_occupation = models.get(model_name).slot_occupation
            obj.geometry.width = models.get(model_name).width
            obj.geometry.depth = models.get(model_name).depth
        elif isinstance(obj, Box):
            obj.geometry.faces = models.get(model_name).faces
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object geometry model is not defined."
            )

    @validator("constructions")
    def _validate_building_constructions(cls, building_constructions: BuildingConstruction, values: Dict):
        cls._validate_rooms(building_constructions.rooms, values["models"])
        return building_constructions

    @classmethod
    def _validate_rooms(cls, rooms: Dict, models: Model):
        for room_id, room in rooms.items():
            cls._validate_id(room_id)
            cls._validate_room_constructions(room.constructions, models)

    @classmethod
    def _validate_room_constructions(cls, room_construction: RoomConstruction, models: Model):
        cls._validate_boxes(room_construction.boxes, models)
        cls._validate_acus(room_construction.acus, models)
        cls._validate_racks(room_construction.racks, models)
        cls._validate_sensors(room_construction.sensors)

    @classmethod
    def _validate_acus(cls, acus: Dict, models: Model):
        for acu_id, acu in acus.items():
            cls._validate_id(acu_id)
            cls._validate_geometry_models(acu, models.geometry_models.acus)

    @classmethod
    def _validate_boxes(cls, boxes: Dict, models: Model):
        for box_id, box in boxes.items():
            cls._validate_id(box_id)
            cls._validate_geometry_models(box, models.geometry_models.boxes)

    @classmethod
    def _validate_racks(cls, racks: Dict, models: Model):
        for rack_id, rack in racks.items():
            cls._validate_id(rack_id)
            cls._validate_geometry_models(rack, models.geometry_models.racks)
            cls._validate_rack_constructions(rack, rack.constructions, models)

    @classmethod
    def _validate_rack_constructions(cls, rack: Rack, rack_constructions: RackConstruction, models: Model):
        cls._validate_servers(rack, rack_constructions.servers, models)

    @classmethod
    def _validate_servers(cls, rack: Rack, servers: Dict, models: Model):
        for server_id, server in servers.items():
            cls._validate_id(server_id)
            cls._validate_geometry_models(server, models.geometry_models.servers)
            cls._validate_server_occupation(rack, server, server_id)

    @classmethod
    def _validate_server_occupation(cls, rack: Rack, server: Server, server_id: str):
        occupied_rack_slot = {}
        slot_position = int(server.geometry.slot_position)
        slot_occupation = int(server.geometry.slot_occupation)
        num_slots = int(rack.geometry.slot)
        if slot_position < 1 or slot_occupation + slot_occupation > num_slots + 1:
            raise ValueError(
                f"invalid server slot/occupation:"
                f"Server({server_id}, slot={slot_position},"
                f"occupation={slot_occupation})"
            )
        for i in range(slot_position, slot_position + slot_occupation):
            if i not in occupied_rack_slot:
                occupied_rack_slot[i] = server_id
            else:
                raise ValueError(
                    f"invalid server slot/occupation: "
                    f"Server({server_id}) has collision with "
                    f"Server({occupied_rack_slot[i]})"
                )

    @classmethod
    def _validate_sensors(cls, sensors: Dict):
        for _id, obj in sensors.items():
            cls._validate_id(_id)

    @property
    def rooms(self) -> list:
        return list(self.constructions.rooms.values())

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2))

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "Building":
        with open(file_path) as f:
            return cls(**convert_json_file(json.load(f)))
