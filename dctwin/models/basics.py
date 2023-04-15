"""Basic geometry
Unit: m
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, validator


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
        return round(v, 3)


class Face(str, Enum):
    front = "front"
    rear = "rear"
    left = "left"
    right = "right"
    top = "top"
    bottom = "bottom"


class BoxFaces(BaseModel):
    top: bool
    bottom: bool
    front: bool
    rear: bool
    left: bool
    right: bool

class ACUFace(BaseModel):
    side: Face
    width: float
    length: float
    offset: Vertex


class Opening(BaseModel):
    location: Vertex
    size: Size
    velocity: Optional[Size] = None
