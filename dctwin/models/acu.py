"""Air conditioning unit (ACU)
"""

from typing import Optional, OrderedDict
from pydantic import BaseModel, Field

from .basics import Size, Vertex, Face


class ACUFace(BaseModel):
    side: Face
    width: float
    length: float
    offset: Vertex


class ACUGeometry(BaseModel):
    model: str = ""
    orientation: int
    location: Vertex

    size: Optional[Size] = None
    supply_face: Optional[ACUFace] = None
    return_face: Optional[ACUFace] = None

    def calculate_face_area(self, face: Face) -> float:
        if face in (Face.front, Face.rear):
            return self.size.dx / 2 * self.size.dz / 2
        if face in (Face.left, Face.right):
            return self.size.dx / 2 * self.size.dz / 2
        if face in (Face.bottom, Face.top):
            return self.size.dx / 2 * self.size.dz / 2
        raise ValueError(f"No such face: {face}")

    @property
    def supply_area(self):
        return self.calculate_face_area(self.supply_face.side)

    @property
    def return_area(self):
        return self.calculate_face_area(self.return_face.side)


class ACUCooling(BaseModel):
    """ ACU cooling properties
    """
    type: str = "DX"
    capacity: float = 0.0
    supply_air_temperature: float = 0.0
    supply_air_volume: float


class ACUPower(BaseModel):
    """ ACU power properties
    """
    fan_power: float = 0.0


class ACU(BaseModel):
    """ ACU object in a data center
    """
    geometry: ACUGeometry
    constructions: None
    meta: Optional[OrderedDict] = Field(default_factory=dict)
    cooling: Optional[ACUCooling] = None
    power: Optional[ACUPower] = None
