"""Air conditioning unit (ACU)
"""

from typing import Optional, OrderedDict
from pydantic import Field

from .basics import Size, Vertex, Face
from .utils import BaseModel


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
    model: Optional[str]
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


class ACUCoolingModel(BaseModel):
    """Model of ACU cooling properties"""

    cooling_type: Optional[str]  # DX, CW, etc.
    cooling_capacity: Optional[float]  # unit(kW)


class ACUCooling(ACUCoolingModel):
    """ACU cooling properties"""

    model: Optional[str]
    supply_air_temperature: Optional[float]  # unit(C)
    supply_air_volume_flow_rate: Optional[float]  # unit(m3/s)


class ACUPowerModel(BaseModel):
    """Model of ACU power properties"""

    rated_fan_power: Optional[float]  # unit(W)


class ACUPower(ACUPowerModel):
    """ACU power properties"""

    model: Optional[str]
    fan_power: Optional[float]  # unit(W)


class ACU(BaseModel):
    """ACU object in a data center"""

    geometry: ACUGeometry = Field(default_factory=ACUGeometry)
    cooling: ACUCooling = Field(default_factory=ACUCooling)
    power: ACUPower = Field(default_factory=ACUPower)
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    @property
    def k(self) -> float:
        """turbulent kinetic energy
        Others:
        omega = epsilon / (0.09 * k)
        """
        tu = 0.1
        u = float(self.cooling.supply_air_volume_flow_rate / self.geometry.supply_area)
        k = 1.5 * ((tu / 100) ** 2) * (u**2)
        return k

    @property
    def epsilon(self) -> float:
        """
        turbulent dissipation rate
        """
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k**2) / (nu * eddy_viscosity_ratio)
