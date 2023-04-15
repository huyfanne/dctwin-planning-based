"""Basic Constructions
"""
from typing import Optional, OrderedDict
from pydantic import BaseModel

from .objects import (
    Plane,
    Box,
    ACU,
    Rack,
    Server,
    Sensor,
)


class RackConstruction(BaseModel):
    servers: OrderedDict[str, Server]


class RoomConstructions(BaseModel):
    raised_floor: Optional[Plane]
    false_ceiling: Optional[Plane]
    boxes: Optional[OrderedDict[str, Box]]
    acus: OrderedDict[str, ACU]
    racks: OrderedDict[str, Rack]
    sensors: OrderedDict[str, Sensor]
