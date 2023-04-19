"""
Object models can be re-used to construct the same object in the building.
"""
from typing import Optional, OrderedDict
from pydantic import BaseModel

from .server import ServerGeometryrModel
from .rack import RackGeometryModel
from .acu import ACUGeometryModel
from .box import BoxGeometryModel


class GeometryModel(BaseModel):
    """ Object standard geometry """
    acus: Optional[OrderedDict[str, ACUGeometryModel]] = None
    racks: Optional[OrderedDict[str, RackGeometryModel]] = None
    servers: Optional[OrderedDict[str, ServerGeometryrModel]] = None
    boxes: Optional[OrderedDict[str, BoxGeometryModel]] = None


class PowerModel(BaseModel):
    """ Object standard power property """
    pass


class Model(BaseModel):
    """ Models is used to define the object models of the building """
    geometry_models: GeometryModel = None
    power_models: PowerModel = None
