from typing import List, Optional, OrderedDict

from ..basics import (
    Face,
    Size,
    Vertex,
    Opening,
    ACUFace,
    BoxFaces,
)
from .models import (
    BoxModel,
    ACUModel,
    RackModel,
    ServerModel,
)
from pydantic import Field
from dctwin.models.utils import BaseModel


class PlaneGeometry(BaseModel):
    height: float
    openings: OrderedDict[str, Opening] = Field(default_factory=dict)


class BoxGeometry(BoxModel):
    model: str
    size: Size
    location: Vertex
    faces: Optional[BoxFaces] = None


class ACUGeometry(ACUModel):
    model: str = ""
    orientation: int
    location: Vertex

    size: Optional[Size] = None
    supply_face: Optional[ACUFace] = None
    return_face: Optional[ACUFace] = None

    min_temperature: Optional[float] = None
    flow_rate: Optional[float] = None
    cooling_capacity: Optional[float] = None

    def calculate_face_area(self, face: Face) -> float:
        if face in (Face.front, Face.rear):
            return self.size.x / 2 * self.size.z / 2
        if face in (Face.left, Face.right):
            return self.size.x / 2 * self.size.z / 2
        if face in (Face.bottom, Face.top):
            return self.size.x / 2 * self.size.z / 2
        raise ValueError(f"No such face: {face}")

    @property
    def supply_area(self):
        return self.calculate_face_area(self.supply_face.side)

    @property
    def return_area(self):
        return self.calculate_face_area(self.return_face.side)

    @property
    def k(self) -> float:
        """turbulent kinetic energy
        Others:
        omega = epsilon / (0.09 * k)
        """
        tu = 0.1
        u = float(self.flow_rate / self.supply_area)
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


class ServerGeometry(ServerModel):
    """
    depth: server depth
    occupation: How many slots the server will occupy
    rated_power: unit(W)
    extend_to_rack_width: extend the server width to equal the rack width or not
    """

    model: str
    slot_position: int

    orientation: Optional[int] = None
    depth: Optional[float] = None
    slot_occupation: Optional[int] = None
    width: Optional[float] = None
    heat_load: Optional[float] = None
    flow_rate: Optional[float] = None

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


class RackGeometry(RackModel):
    model: str
    location: Vertex
    orientation: int
    has_blanking_panel: bool

    size: Optional[Size] = None
    slot: Optional[int] = None
    first_slot_offset: Optional[float] = None


class SensorGeometry(BaseModel):
    location: Vertex


class RoomGeometry(BaseModel):
    height: float
    plane: List[Vertex]
