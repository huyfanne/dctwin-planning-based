import json
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, OrderedDict, Union

from pydantic import BaseModel, Field, validator

from dctwin.models.basics import Probe, Size, Vertex
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


class Containment(BaseModel):
    size: Size
    placement: Vertex
    front: bool = True
    rear: bool = True
    left: bool = True
    right: bool = True
    top: bool = True
    bottom: bool = True


class Duct(BaseModel):
    placement: Vertex
    size: Size


class Ceiling(BaseModel):
    height: float
    duct_list: List[Duct] = Field(default_factory=list)


class Opening(BaseModel):
    placement: Vertex
    size: Size


class RaisedFloor(BaseModel):
    height: float
    opening_list: List[Opening] = Field(default_factory=list)


class Constructions(BaseModel):
    partition_walls: OrderedDict[str, PartitionWall] = Field(default_factory=dict)
    containments: OrderedDict[str, Containment] = Field(default_factory=dict)
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
    probes: List[Probe] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: float}

    @validator("probes")
    def update_probes(cls, v):
        for index, probe in enumerate(v):
            if probe.name is None:
                probe.name = f"Probe_{index + 1}"
        return v

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
