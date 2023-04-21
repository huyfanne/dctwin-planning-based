""" Room object
"""
import numpy as np
from typing import Optional, OrderedDict, List, Tuple, Dict, Union

from loguru import logger
from pydantic import BaseModel, Field

from .basics import Vertex, Face
from .panel import Panel
from .box import Box
from .rack import Rack
from .sensor import Sensor
from .acu import ACU, ACUFace
from .server import Server
from .utils import rotate, euclidean_distance


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

        def get_raw_point(face: ACUFace) -> Tuple[float, float, float]:
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

        def get_center_coordinate(face: ACUFace) -> Vertex:
            x, y, z = get_raw_point(face)
            x, y = rotate(
                (acu.geometry.location.x, acu.geometry.location.y), (x, y), acu.geometry.orientation
            )
            return Vertex(x=round(x, 3), y=round(y, 3), z=z)

        inlet = get_center_coordinate(acu.geometry.return_face)
        outlet = get_center_coordinate(acu.geometry.supply_face)

        return inlet, outlet

    def _parse_server_model(self, type_: str) -> Union[List[str], Dict[str, str]]:
        server_type_dict = {}
        server_type_list = []
        for rack_key, rack in self.constructions.racks.items():
            for server_key, server in rack.constructions.servers.items():
                if server.geometry.model is not None:
                    server_type_dict[server_key] = server.geometry.model
                    if server.geometry.model not in server_type_list:
                        server_type_list.append(server.geometry.model)
                else:
                    logger.warning(f"server {server_key} model is not defined")
        if type_ == "list":
            return server_type_list
        elif type_ == "dict":
            return server_type_dict

    @property
    def num_crac(self) -> int:
        return len(self.constructions.acus.items())

    @property
    def num_ser(self) -> int:
        count = 0
        for rack in self.constructions.racks.values():
            for _ in rack.constructions.servers.values():
                count += 1
        return count

    @property
    def num_sen(self) -> int:
        return len(self.constructions.sensors.items())

    @property
    def acu_keys(self) -> List[str]:
        return list(self.constructions.acus.keys())

    @property
    def rack_keys(self) -> List[str]:
        return list(self.constructions.racks.keys())

    @property
    def server_keys(self) -> List[str]:
        server_key_list = []
        for rack in self.constructions.racks.values():
            for server_key, _ in rack.constructions.servers.items():
                server_key_list.append(server_key)
        return server_key_list

    @property
    def sensor_keys(self) -> List[str]:
        return list(self.constructions.sensors.keys())

    @property
    def acus(self) -> List[ACU]:
        return list(self.constructions.acus.values())

    @property
    def racks(self) -> List[Rack]:
        return list(self.constructions.racks.values())

    @property
    def servers(self) -> List[Server]:
        server_list = []
        for rack in self.constructions.racks.values():
            for server in rack.constructions.servers.values():
                server_list.append(server)
        return server_list

    @property
    def sensors(self) -> List[Sensor]:
        return list(self.constructions.sensors.values())

    @property
    def server_model_list(self) -> List[str]:
        return self._parse_server_model(type_="list")

    @property
    def server_model_dict(self) -> Dict[str, str]:
        return self._parse_server_model(type_="dict")

    @property
    def acu2sen(self) -> np.ndarray:
        """ Get the distance matrix of the ACU to sensor connections
        """
        acu2sen_dis = np.zeros([self.num_crac, self.num_sen])
        for acu_idx, acu in enumerate(self.acus):
            for sen_idx, sen in enumerate(self.sensors):
                acu_loc = acu.geometry.location
                sen_loc = sen.geometry.location
                acu2sen_dis[acu_idx][sen_idx] = euclidean_distance(acu_loc, sen_loc)
        return acu2sen_dis

    @property
    def ser2sen(self) -> np.ndarray:
        """ Get the distance matrix of the server to sensor connections
        """
        ser2sen_dis = np.zeros([self.num_ser, self.num_sen])
        for rack in self.racks:
            for ser_idx, (ser_key, ser) in enumerate(rack.constructions.servers.items()):
                for sen_idx, sen in enumerate(self.sensors):
                    ser_loc_i, ser_loc_o = self.server_patch_positions(ser_key)
                    sen_loc = sen.geometry.location
                    ser2sen_dis[ser_idx][sen_idx] = euclidean_distance(ser_loc_o, sen_loc)
        return ser2sen_dis

    @property
    def acu2ser(self) -> np.ndarray:
        """ Get the distance matrix of the acu to server connections
        """
        acu2ser_dis = np.zeros([self.num_crac, self.num_ser])
        for acu_idx, acu in enumerate(self.acus):
            for rack in self.racks:
                for ser_idx, (ser_key, ser) in enumerate(rack.constructions.servers.items()):
                    acu_loc = acu.geometry.location
                    ser_loc, _ = self.server_patch_positions(ser_key)
                    acu2ser_dis[acu_idx][ser_idx] = euclidean_distance(acu_loc, ser_loc)
        return acu2ser_dis

    def _update_acu_boundaries(
        self,
        supply_air_temperatures: Dict,
        supply_air_volume_flow_rates: Dict,
    ) -> None:
        for acu_uid, acu in self.constructions.acus.items():
            if supply_air_temperatures is not None:
                try:
                    acu.cooling.supply_air_temperature = supply_air_temperatures[acu_uid]
                except KeyError:
                    logger.critical(f"ACU {acu_uid} setpoint is missing")
            if supply_air_volume_flow_rates is not None:
                try:
                    acu.cooling.supply_air_volume_flow_rate = supply_air_volume_flow_rates[acu_uid]
                except KeyError:
                    logger.critical(f"ACU {acu_uid} volume flow rate is missing")

    def _update_server_boundaries(
        self,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
    ) -> None:
        for rack in self.racks:
            for server_uid, server in rack.constructions.servers.items():
                if server_powers is not None:
                    try:
                        server.power.input_power = server_powers[server_uid]
                    except KeyError:
                        logger.critical(f"server {server_uid} power is missing")
                if server_volume_flow_rates is not None:
                    try:
                        server.cooling.volume_flow_rate = server_volume_flow_rates[server_uid]
                    except KeyError:
                        logger.critical(f"server {server_uid} volume flow rate is missing")

    def update_boundary_conditions(
        self,
        supply_air_temperatures: Dict = None,
        supply_air_volume_flow_rates: Dict = None,
        server_powers: Dict = None,
        server_volume_flow_rates: Dict = None,
    ) -> None:
        self._update_acu_boundaries(supply_air_temperatures, supply_air_volume_flow_rates)
        self._update_server_boundaries(server_powers, server_volume_flow_rates)

    @property
    def format_boundary_conditions(self) -> Dict:
        boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
        }
        for rack in self.racks:
            for uid, server in rack.constructions.servers.items():
                boundary_conditions["server_powers"][uid] = server.power.input_power
                boundary_conditions["server_volume_flow_rates"][uid] = server.cooling.volume_flow_rate
        for uid, acu in self.constructions.acus.items():
            boundary_conditions["supply_air_temperatures"][uid] = acu.cooling.supply_air_temperature
            boundary_conditions["supply_air_volume_flow_rates"][uid] = acu.cooling.supply_air_volume_flow_rate

        return boundary_conditions
