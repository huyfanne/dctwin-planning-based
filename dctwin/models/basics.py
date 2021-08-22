"""Basic geometry
Unit: m
"""
from enum import Enum

from pydantic import BaseModel, validator


class Size(BaseModel):
    dx: float
    dy: float
    dz: float

    @validator("dx", "dy", "dz")
    def float_check(cls, v):
        return round(v, 3)


class Vertex(BaseModel):
    x: float
    y: float
    z: float

    @validator("x", "y", "z")
    def float_check(cls, v):
        return round(v, 3)


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
    flow_rate: float
    heat_load: float
