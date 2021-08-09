import json
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, OrderedDict, Union

from pydantic import BaseModel, Field, validator

from dctwin.models.basics import ACUConfig, Face, RoomConfig, ServerConfig, Size, Vertex
from dctwin.models.objects import Objects


class VentOpening(BaseModel):
    width: float
    length: float
    offset_h: float
    offset_v: float


class PartitionWall(BaseModel):
    size: Size
    placement: Vertex
    vent_opening_list: List[VentOpening] = Field(default_factory=list)


class Duct(BaseModel):
    placement: Vertex
    size: Size
    extend_to_floor: Optional[List[Face]]


class Ceiling(BaseModel):
    height: float
    duct_in_list: List[Duct]
    duct_out_list: List[Duct]


class RaisedFloor(BaseModel):
    placement: Vertex


class Constructions(BaseModel):
    partition_walls: OrderedDict[str, PartitionWall]
    raised_floor: Optional[RaisedFloor]
    ceiling: Optional[Ceiling]


class Room(BaseModel):
    name: str
    height: float
    plane_outline: List[Vertex]

    version: str = "0.1"
    constructions: Constructions
    objects: Objects

    # Probe locations
    probes: List[Vertex] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: float}

    @validator("objects")
    def validate_objects(cls, v):
        for server in v.servers.values():
            rack = v.racks[server.rack_id]
            server.orientation = rack.orientation
            server.width = v.rack_models[rack.model].size.dx
        return v

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2))

    @classmethod
    def load(cls, file_path: "str") -> "Room":
        with open(file_path) as f:
            return cls(**json.load(f))
