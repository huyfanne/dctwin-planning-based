"""Basic geometry
Unit: m
"""
from decimal import Decimal
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel
from pydantic.fields import Field


class Size(BaseModel):
    dx: float
    dy: float
    dz: float


class Vertex(BaseModel):
    x: float
    y: float
    z: float


class Face(str, Enum):
    front = "front"
    rear = "rear"
    left = "left"
    right = "right"
    top = "top"
    bottom = "bottom"


class ACUConfig(BaseModel):
    supply_temperature: float
    fan_speed_ratio: float
    flow_rate: float


class ServerConfig(BaseModel):
    # load_ratio: float
    flow_rate: float
    heat_load: float


class RoomConfig(BaseModel):
    acu_configs: Dict[str, ACUConfig]
    server_configs: Dict[str, ServerConfig]
    probes: List[Vertex] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: float}
