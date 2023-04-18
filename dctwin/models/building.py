"""
Building is the highest level object in a data center.
It contains all the data halls (rooms).
"""

import json
from pathlib import Path
from typing import Union, Optional, Dict, OrderedDict
from pydantic import BaseModel, validator
from dctwin.models.room import Room
from .utils import convert_json_file


class BuildingGeometry(BaseModel):
    """ Building geometry is used to define the geometry of the building """
    pass


class BuildingConstruction(BaseModel):
    """ Building construction is used to define the data halls in a building """
    rooms: OrderedDict[str, Room]


class Building(BaseModel):
    """ Building object
    """
    geometry: Optional[BuildingGeometry]
    constructions: BuildingConstruction
    models: Optional[None]
    inputs: Optional[None]
    meta: Optional[Dict] = {}

    @classmethod
    def _validate_geometry_models(cls, _id: str, obj: Dict, models: Dict):
        model_name = obj["geometry"]["model"]
        if models.get(model_name) is not None:
            obj["geometry"] = {
                **obj["geometry"],
                **models.get(model_name),
            }
        else:
            raise ValueError(f"{obj} model name does not exists: {_id}")

    @classmethod
    def _validate_id(cls, _id: str):
        if not _id.isidentifier():
            raise ValueError(f"must be valid identifier: {_id}")

    @validator("constructions")
    def validate_building_constructions(cls, v, values):
        cls._validate_rooms(v, values["models"])

    @classmethod
    def _validate_rooms(cls, rooms: Dict, models: Dict):
        for _id, obj in rooms.items():
            cls._validate_id(_id)
            room_constructions = obj["constructions"]
            cls._validate_room_constructions(room_constructions, models)

    @classmethod
    def _validate_room_constructions(cls, room_construction: Dict, models: Dict):
        cls._validate_boxes(room_construction["boxes"], models)
        cls._validate_acus(room_construction["acus"], models)
        cls._validate_racks(room_construction["racks"], models)
        cls._validate_sensors(room_construction["sensors"])

    @classmethod
    def _validate_acus(cls, acus: dict, models: dict):
        for _id, obj in acus.items():
            cls._validate_id(_id)
            cls._validate_geometry_models(_id, obj, models["geometry_models"]["acus"])
    
    @classmethod
    def _validate_boxes(cls, boxes: Dict, models: Dict):
        for _id, obj in boxes.items():
            cls._validate_id(_id)
            cls._validate_geometry_models(_id, obj, models["geometry_models"]["boxes"])

    @classmethod
    def _validate_racks(cls, racks: Dict, models: Dict):
        for _id, obj in racks.items():
            cls._validate_id(_id)
            cls._validate_geometry_models(_id, obj, models["geometry_models"]["racks"])
            rack_constructions = obj["constructions"]
            cls._validate_rack_constructions(obj, rack_constructions, models)
    
    @classmethod
    def _validate_rack_constructions(cls, rack: Dict, rack_constructions: Dict, models: Dict):
        cls._validate_servers(rack, rack_constructions["servers"], models)

    @classmethod
    def _validate_servers(cls, rack: Dict, servers: Dict, models: Dict):
        occupied_rack_slot = {}
        for _id, obj in servers.items():
            cls._validate_id(_id)
            cls._validate_geometry_models(_id, obj, models["geometry_models"]["servers"])
            slot_position = int(obj["geometry"]["slot_position"])
            slot_occupation = int(obj["geometry"]["slot_occupation"])
            num_slots = int(rack["geometry"]["slot"])
            if slot_position < 1 or slot_occupation + slot_occupation > num_slots + 1:
                raise ValueError(
                    f"invalid server slot/occupation:"
                    f"Server({_id}, slot={obj['geometry']['slot_position']},"
                    f"occupation={obj['geometry']['slot_occupation']})"
                )

            for i in range(slot_position, slot_position + slot_occupation):
                if i not in occupied_rack_slot:
                    occupied_rack_slot[i] = _id
                else:
                    raise ValueError(
                        f"invalid server slot/occupation: "
                        f"Server({_id}) has collision with "
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
