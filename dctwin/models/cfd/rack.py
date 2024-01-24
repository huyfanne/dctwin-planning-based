"""Rack object in a data center
"""
from typing import Optional, OrderedDict
from pydantic import Field

from .basics import Size, Vertex
from .box import BoxFaces
from .server import Server
from .utils import BaseModel


class RackGeometryModel(BaseModel):
    size: Optional[Size]
    slot: Optional[int]
    first_slot_offset: Optional[float]
    faces: Optional[BoxFaces]


class RackGeometry(RackGeometryModel):
    model: Optional[str]
    location: Vertex
    orientation: int
    has_blanking_panel: bool


class RackConstruction(BaseModel):
    """Rack construction is used to define the servers in a rack"""

    servers: OrderedDict[str, Server]


class Rack(BaseModel):
    """Rack object in a data  center"""

    geometry: RackGeometry
    constructions: Optional[RackConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)
