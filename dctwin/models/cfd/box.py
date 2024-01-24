""" Box object
"""
from typing import Optional, OrderedDict
from pydantic import Field

from .basics import Size, Vertex, Opening, Face
from .utils import BaseModel


class BoxFaces(BaseModel):
    top: bool
    bottom: bool
    front: bool
    rear: bool
    left: bool
    right: bool


class BoxGeometryModel(BaseModel):
    faces: Optional[BoxFaces]


class BoxGeometry(BoxGeometryModel):
    model: Optional[str]
    location: Vertex
    size: Size
    openings_side: Optional[Face]
    openings: Optional[OrderedDict[str, Opening]]


class Box(BaseModel):
    """A box is an abstract 3D object with a size and location in space."""

    geometry: BoxGeometry
    meta: Optional[OrderedDict] = Field(default_factory=dict)
