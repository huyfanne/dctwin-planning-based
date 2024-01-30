"""Server object model in a data center
"""

from typing import Optional, OrderedDict
from pydantic import Field

from .utils import BaseModel
from .basics import Vertex, Face


class ServerFace(BaseModel):
    side: Face
    width: float
    length: float
    offset: Vertex


class ServerGeometryrModel(BaseModel):
    slot_occupation: Optional[int]
    depth: Optional[float]
    width: Optional[float]
    inlet_face: Optional[ServerFace]
    outlet_face: Optional[ServerFace]


class ServerGeometry(ServerGeometryrModel):
    """
    depth: server depth
    occupation: How many slots the server will occupy
    extend_to_rack_width: extend the server width to equal the rack width or not
    """

    model: Optional[str]
    slot_position: int
    orientation: Optional[float]

    @property
    def height(self) -> float:
        return self.slot_occupation * 0.045

    @property
    def inlet_area(self) -> float:
        return self.height * float(self.width)

    @property
    def outlet_area(self) -> float:
        return self.height * float(self.width)


class ServerCoolingModel(BaseModel):
    """Model of server cooling properties"""

    fan_type: Optional[str] = "Fixed"  # Fixed or Variable
    volume_flow_rate_ratio: Optional[float] = None  # unit(m3/s/W)
    volume_flow_rate: Optional[float]  # unit(m3/s)


class ServerCooling(ServerCoolingModel):
    """Server cooling properties"""

    model: Optional[str]


class ServerPowerModel(BaseModel):
    """Model of server power properties"""

    rated_power: Optional[float]  # unit(W)


class ServerPower(ServerPowerModel):
    """Server power properties"""

    model: Optional[str]
    input_power: Optional[float]  # unit(W)


class Server(BaseModel):
    geometry: ServerGeometry = Field(default_factory=ServerGeometry)
    cooling: ServerCooling = Field(default_factory=ServerCooling)
    power: ServerPower = Field(default_factory=ServerPower)
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    @property
    def k(self) -> float:
        tu = 0.1
        u = float(self.volume_flow_rate) / self.geometry.outlet_area
        k = 1.5 * ((tu / 100) ** 2) * (u**2)
        return k

    @property
    def epsilon(self) -> float:
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k**2) / (nu * eddy_viscosity_ratio)

    @property
    def volume_flow_rate(self) -> float:
        if self.cooling.fan_type == "Fixed":
            assert (
                self.cooling.volume_flow_rate is not None
            ), "Please specify the constant server volume flow rate."
            server_volume_flow_rate = self.cooling.volume_flow_rate
        elif self.cooling.fan_type == "Variable":
            assert (
                self.cooling.volume_flow_rate_ratio is not None
            ), "Please specify the volume flow rate ratio in terms of input power."
            server_volume_flow_rate = (
                self.cooling.volume_flow_rate_ratio * self.power.input_power
            )
        else:
            raise ValueError("Invalid fan type.")

        return server_volume_flow_rate
