"""
Object models can be re-used to construct the same object in the building.
"""
from typing import Optional, OrderedDict
from pydantic import Field

from .server import ServerGeometryrModel, ServerCoolingModel, ServerPowerModel
from .rack import RackGeometryModel
from .acu import ACUGeometryModel, ACUCoolingModel, ACUPowerModel
from .box import BoxGeometryModel
from .utils import BaseModel


class GeometryModel(BaseModel):
    """Object standard geometry"""

    acus: Optional[OrderedDict[str, ACUGeometryModel]] = None
    racks: Optional[OrderedDict[str, RackGeometryModel]] = None
    servers: Optional[OrderedDict[str, ServerGeometryrModel]] = None
    boxes: Optional[OrderedDict[str, BoxGeometryModel]] = None


class CoolingModel(BaseModel):
    """Object standard cooling property"""

    acus: Optional[OrderedDict[str, ACUCoolingModel]] = None
    servers: Optional[OrderedDict[str, ServerCoolingModel]] = None


class PowerModel(BaseModel):
    """Object standard power property"""

    acus: Optional[OrderedDict[str, ACUPowerModel]] = None
    servers: Optional[OrderedDict[str, ServerPowerModel]] = None


class Model(BaseModel):
    """Models is used to define the object models of the building"""

    geometry_models: Optional[GeometryModel] = Field(default_factory=GeometryModel)
    cooling_models: Optional[CoolingModel] = Field(default_factory=CoolingModel)
    power_models: Optional[PowerModel] = Field(default_factory=PowerModel)
