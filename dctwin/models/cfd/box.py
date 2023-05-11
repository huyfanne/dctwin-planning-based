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
    model: str
    location: Vertex
    size: Size
    openings_side: Optional[Face]
    openings: Optional[OrderedDict[str, Opening]]


class BoxConstruction(BaseModel):
    """ Box construction is used to define openings in a box
    """
    openings: OrderedDict[str, Opening] = Field(default_factory=dict)


class Box(BaseModel):
    """ A box is an abstract 3D object with a size and location in space.
    """
    geometry: BoxGeometry
    constructions: Optional[BoxConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)

