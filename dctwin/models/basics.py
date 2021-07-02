"""Basic geometry
Unit: m
"""
from decimal import Decimal
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel
from pydantic.fields import Field


class Size(BaseModel):
    dx: Decimal
    dy: Decimal
    dz: Decimal


class Vertex(BaseModel):
    x: Decimal
    y: Decimal
    z: Decimal


class Face(str, Enum):
    front = 'front'
    rear = 'rear'
    left = 'left'
    right = 'right'
    top = 'top'
    bottom = 'bottom'


class ACUConfig(BaseModel):
    supply_temperature: Decimal
    fan_speed_ratio: Decimal
    flow_rate: Decimal


class ServerConfig(BaseModel):
    # load_ratio: Decimal
    flow_rate: Decimal
    heat_load: Decimal


class RoomConfig(BaseModel):
    acu_configs: Dict[str, ACUConfig]
    server_configs: Dict[str, ServerConfig]
    probes: List[Vertex] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: float}
