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


class ACUGeometryModel(BaseModel):
    size: Optional[Size]
    supply_face: Optional[ACUFace]
    return_face: Optional[ACUFace]


class ACUGeometry(ACUGeometryModel):
    model: str
    orientation: int
    location: Vertex

    def calculate_face_area(self, face: Face) -> float:
        if face in (Face.front, Face.rear):
            return self.size.x / 2 * self.size.z / 2
        if face in (Face.left, Face.right):
            return self.size.y / 2 * self.size.z / 2
        if face in (Face.bottom, Face.top):
            return self.size.x / 2 * self.size.y / 2
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
    cooling_type: Optional[str]
    cooling_capacity: float # unit(kW)
    supply_air_temperature: float # unit(C)
    supply_air_volume_flow_rate: float # unit(m3/s)


class ACUPower(BaseModel):
    """ ACU power properties
    """
    fan_power: Optional[float] # unit(W)


class ACU(BaseModel):
    """ ACU object in a data center
    """
    geometry: ACUGeometry
    meta: Optional[OrderedDict] = Field(default_factory=dict)
    cooling: ACUCooling = Field(default_factory=ACUCooling)
    power: ACUPower = Field(default_factory=ACUPower)

    @property
    def k(self) -> float:
        """turbulent kinetic energy
        Others:
        omega = epsilon / (0.09 * k)
        """
        tu = 0.1
        u = float(self.cooling.supply_air_volume_flow_rate / self.geometry.supply_area)
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        """
        turbulent dissipation rate
        """
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)
