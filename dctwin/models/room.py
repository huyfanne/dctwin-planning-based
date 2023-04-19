""" Room object
"""

from typing import Optional, OrderedDict, List, Tuple
from pydantic import BaseModel, Field

from .basics import Vertex, Face
from .panel import Panel
from .box import Box
from .rack import Rack
from .sensor import Sensor
from .acu import ACU
from .utils import rotate


class RoomGeometry(BaseModel):
    model: str = ""
    height: float
    plane: List[Vertex]


class RoomConstruction(BaseModel):
    """ Room construction is used to define the objects in a room
    """
    raised_floor: Optional[Panel]
    false_ceiling: Optional[Panel]
    boxes: Optional[OrderedDict[str, Box]]
    acus: OrderedDict[str, ACU]
    racks: OrderedDict[str, Rack]
    sensors: OrderedDict[str, Sensor]


class Room(BaseModel):

    geometry: RoomGeometry
    constructions: Optional[RoomConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    def server_patch_positions(self, server_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of server inlet and outlet"""

        for rack_id, rack in self.constructions.racks.items():
            if server_id in rack.constructions.servers:
                server = rack.constructions.servers.get(server_id)
                server_rack = rack
                rack: Rack = server_rack

                z = rack.geometry.location.z + rack.geometry.first_slot_offset + 0.045 * (
                        server.geometry.slot_position - 1)
                z = round(z, 3)

                # inlet
                inlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                inlet_y = rack.geometry.location.y

                inlet_x, inlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y), (inlet_x, inlet_y), rack.geometry.orientation
                )
                inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

                # outlet
                outlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                outlet_y = rack.geometry.location.y + server.geometry.depth
                outlet_x, outlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y), (outlet_x, outlet_y), rack.geometry.orientation
                )
                outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y, 3), z=z)
                return inlet, outlet

        else:
            raise ValueError(f"Server {server_id} not found")

    def acu_patch_positions(self, acu_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of acu return and supply"""
        acu: ACU = self.constructions.acus.get(acu_id)

        def get_raw_point(face):
            if face.side == Face.front:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.rear:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.left:
                x = acu.geometry.location.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.right:
                x = acu.geometry.location.x + acu.geometry.size.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.top:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = acu.geometry.size.z
            elif face.side == Face.bottom:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = 0
            else:
                raise ValueError(f"not supported: face.side={face.side}")
            if self.constructions.raised_floor is not None:
                z += self.constructions.raised_floor.geometry.height
            return round(x, 3), round(y, 3), round(z, 3)

        def get_center_coordinate(face):
            x, y, z = get_raw_point(face)
            x, y = rotate(
                (acu.geometry.location.x, acu.geometry.location.y), (x, y), acu.geometry.orientation
            )
            return Vertex(x=round(x, 3), y=round(y, 3), z=z)

        inlet = get_center_coordinate(acu.geometry.return_face)
        outlet = get_center_coordinate(acu.geometry.supply_face)

        return inlet, outlet

    @property
    def acus(self):
        return list(self.constructions.acus.values())

    @property
    def racks(self):
        return list(self.constructions.racks.values())

    @property
    def servers(self):
        server_list = []
        for rack in self.constructions.racks.values():
            for server in rack.constructions.servers.values():
                server_list.append(server)
        return server_list

    @property
    def sensors(self):
        return list(self.constructions.sensors.values())
