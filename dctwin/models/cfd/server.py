"""Server object model in a data center
"""

from typing import Optional, OrderedDict
from pydantic import BaseModel, Field


class ServerGeometryrModel(BaseModel):
    slot_occupation: Optional[int]
    depth: Optional[float]
    width: Optional[float]


class ServerGeometry(ServerGeometryrModel):
    """
    depth: server depth
    occupation: How many slots the server will occupy
    extend_to_rack_width: extend the server width to equal the rack width or not
    """
    model: str
    slot_position: int
    orientation: Optional[float]

    @property
    def height(self) -> float:
        return self.slot_occupation * 0.045

    @property
    def inlet_area(self) -> float:
        if self.orientation == 90:
            return -self.height * float(self.width)
        else:
            return self.height * float(self.width)

    @property
    def outlet_area(self) -> float:
        if self.orientation == 90:
            return -self.height * float(self.width)
        else:
            return self.height * float(self.width)


class ServerCooling(BaseModel):
    fan_type: Optional[str] = "Fixed"
    volume_flow_rate: Optional[float] = 0.05 if fan_type == "Fixed" else None # unit(m3/s)
    volume_flow_rate_ratio: Optional[float] # unit(m3/s/W)


class ServerPower(BaseModel):
    rated_power: Optional[float]  # unit(W)
    input_power: Optional[float]  # unit(W)


class Server(BaseModel):
    geometry: ServerGeometry
    meta: Optional[OrderedDict]
    cooling: ServerCooling = Field(default_factory=ServerCooling)
    power: ServerPower = Field(default_factory=ServerPower)

    @property
    def k(self) -> float:
        tu = 0.1
        u = float(self.cooling.volume_flow_rate) / self.geometry.outlet_area
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)
