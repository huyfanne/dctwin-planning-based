from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class ServerModel(BaseModel):
    occupation: int
    depth: float


class Server(BaseModel):
    """
    depth: server depth
    occupation: How many slots the server will occupy
    rated_power: unit(W)
    extend_to_rack_width: extend the server width to equal the rack width or not
    """

    id: str
    rack_id: str
    model: str
    slot: int
    heat_load: Decimal
    flow_rate: float
    # Temperature -> Flow rate, example: 27 -> 0.05
    dynamic_flow_rate_high: Optional[float] = None
    dynamic_temperature_high: Optional[float] = None
    dynamic_temperature_low: Optional[float] = None
    occupation: Optional[int] = None
    orientation: Optional[int] = None
    width: Optional[Decimal] = None

    @property
    def t_sink(self) -> str:
        return f'tSink_{self.id}'

    @property
    def u_sink(self) -> str:
        return f'uSink_{self.id}'

    @property
    def height(self) -> float:
        return self.occupation * 0.05

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

    @property
    def k(self) -> float:
        tu = 0.1
        u = float(self.flow_rate) / self.outlet_area
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)

    @property
    def inlet_name(self) -> str:
        return f'server_inlet_{self.id}'

    @property
    def outlet_name(self) -> str:
        return f'server_outlet_{self.id}'
