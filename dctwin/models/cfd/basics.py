"""Basic geometry
Unit: m (meter)
"""
from enum import Enum
from typing import Optional

from pydantic import validator
from .utils import BaseModel


# noinspection PyMethodParameters
class Vertex(BaseModel):
    x: float
    y: float
    z: float

    @validator("x", "y", "z")
    def float_check(cls, v):
        return round(v, 3)


# noinspection PyMethodParameters
class Size(BaseModel):
    x: float
    y: float
    z: float

    @validator("x", "y", "z")
    def float_check(cls, v):
        return round(v, 5)


class Face(str, Enum):
    front = "front"
    rear = "rear"
    left = "left"
    right = "right"
    top = "top"
    bottom = "bottom"


class Opening(BaseModel):
    location: Vertex
    size: Size
    velocity: Optional[Size] = None
