"""Rack object in a data center
"""
from typing import Optional, OrderedDict
from pydantic import BaseModel, Field

from .basics import Size, Vertex
from .server import Server


class RackGeometryModel(BaseModel):
    slot: int
    size: Size
    first_slot_offset: float


class RackGeometry(RackGeometryModel):
    model: str
    location: Vertex
    orientation: int
    has_blanking_panel: bool

    size: Optional[Size] = None
    slot: Optional[int] = None
    first_slot_offset: Optional[float] = None


class RackConstruction(BaseModel):
    """ Rack construction is used to define the servers in a rack
    """
    servers: OrderedDict[str, Server]


class Rack(BaseModel):
    """ Rack object in a data center """
    geometry: RackGeometry
    constructions: Optional[RackConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)
