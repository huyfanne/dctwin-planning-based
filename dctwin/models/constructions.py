import json
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, OrderedDict, Tuple, TypeVar, Union

from dctwin.models.basics import Face, Size, Vertex
from dctwin.models.geometry_utils import rotate
from dctwin.models.objects import ACU, Objects, Rack, Server
from numpy import outer
from pydantic import BaseModel, Field, validator


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


class Pillar(BaseModel):
    id: str
    size: Size
    placement: Vertex


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
    pillars: OrderedDict[str, Pillar] = Field(default_factory=dict)
    containments: OrderedDict[str, Containment] = Field(default_factory=dict)
    raised_floor: Optional[RaisedFloor]
    ceiling: Optional[Ceiling]

    @validator("partition_walls", pre=True)
    def validate_partition_walls(cls, v):
        for _id, wall in v.items():
            wall["id"] = _id
        return v


class Room(BaseModel):
    name: str
    height: float
    plane_outline: List[Vertex]

    version: str = "0.1"
    constructions: Constructions
    objects: Objects

    class Config:
        json_encoders = {Decimal: float}

    def get_object(self, klass, obj_id: str) -> Union[Server, ACU, Rack]:
        if klass == Server:
            obj = self.objects.servers.get(obj_id)
        elif klass == ACU:
            obj = self.objects.acus.get(obj_id)
        elif klass == Rack:
            obj = self.objects.racks.get(obj_id)
        else:
            raise ValueError("unsupported klass")
        if obj is None:
            raise ValueError(f"not exist: {klass.__name__}(id={obj_id})")
        return obj

    def server_patch_positions(self, server_id: str) -> Tuple[Vertex]:
        """Get the center point position of server inlet and outlet"""
        server: Server = self.get_object(Server, server_id)
        rack: Rack = self.get_object(Rack, server.rack_id)
        rack_model = self.objects.rack_models[rack.model]
        server_model = self.objects.server_models[server.model]

        z = (
            rack_model.first_slot_offset
            + (server.occupation / 2 + server.slot - 1) * 0.05
        )
        if self.constructions.raised_floor is not None:
            z += self.constructions.raised_floor.height
        z = round(z, 3)

        # inlet
        inlet_x = rack.placement.x + rack.size.dx / 2
        inlet_y = rack.placement.y

        inlet_x, inlet_y = rotate(
            (rack.placement.x, rack.placement.y), (inlet_x, inlet_y), rack.orientation
        )
        inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

        # outlet
        outlet_x = inlet_x
        outlet_y = inlet_y + server_model.depth
        outlet_x, outlet_y = rotate(
            (rack.placement.x, rack.placement.y), (outlet_x, outlet_y), rack.orientation
        )
        outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y), z=z)
        return inlet, outlet

    def acu_patch_positions(self, acu_id: str) -> Tuple[Vertex]:
        """Get the center point position of acu return and supply"""
        acu: ACU = self.get_object(ACU, acu_id)
        acu_model = self.objects.acu_models[acu.model]

        def get_raw_point(face):
            if face.side == Face.front:
                x = acu.placement.x + acu.size.dx / 2 + face.offset.x
                y = acu.placement.y
                z = acu.placement.z + acu.size.dz / 2 + face.offset.y
            elif face.side == Face.rear:
                x = acu.placement.x + acu.size.dx / 2 + face.offset.x
                y = acu.placement.y + acu.size.dy
                z = acu.placement.z + acu.size.dz / 2 + face.offset.y
            elif face.side == Face.left:
                x = acu.placement.x
                y = acu.placement.y + acu.size.dy / 2 - face.offset.x
                z = acu.placement.z + acu.size.dz / 2 + face.offset.y
            elif face.side == Face.right:
                x = acu.placement.x + acu.size.dx
                y = acu.placement.y + acu.size.dy / 2 - face.offset.x
                z = acu.placement.z + acu.size.dz / 2 + face.offset.y
            elif face.side == Face.top:
                x = acu.placement.x + acu.size.dx / 2 + face.offset.x
                y = acu.placement.y + acu.size.dy / 2 + face.offset.y
                z = acu.size.dz
            elif face.side == Face.bottom:
                x = acu.placement.x + acu.size.dx / 2 + face.offset.x
                y = acu.placement.y + acu.size.dy / 2 + face.offset.y
                z = 0
            else:
                raise ValueError(f"not supported: face.side={face.side}")
            if self.constructions.raised_floor is not None:
                z += self.constructions.raised_floor.height
            return round(x, 3), round(y, 3), round(z, 3)

        inlet_x, inlet_y, inlet_z = get_raw_point(acu_model.return_face)
        inlet_x, inlet_y = rotate(
            (acu.placement.x, acu.placement.y), (inlet_x, inlet_y), acu.orientation
        )
        inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=inlet_z)

        outlet_x, outlet_y, outlet_z = get_raw_point(acu_model.supply_face)
        outlet_x, outlet_y = rotate(
            (acu.placement.x, acu.placement.y), (outlet_x, outlet_y), acu.orientation
        )
        outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y), z=outlet_z)
        return inlet, outlet

    @property
    def probes(self):
        return list(self.objects.sensors.values())

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
