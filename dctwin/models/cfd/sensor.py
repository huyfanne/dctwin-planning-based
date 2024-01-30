"""Temperature sensor object
"""
from typing import Optional, OrderedDict
from pydantic import Field

from .basics import Vertex
from .utils import BaseModel


class SensorGeometry(BaseModel):
    """Sensor geometry that defines the location of the sensor"""

    location: Vertex


class Sensor(BaseModel):
    """Sensor object in a data center"""

    geometry: SensorGeometry
    meta: Optional[OrderedDict] = Field(default_factory=dict)
