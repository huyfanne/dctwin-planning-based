import math
import numpy as np
from typing import Dict, List
from pathlib import Path
from dctwin.models import Room, Vertex

from loguru import logger


class RoomParser:
    """
    A class to parse the room model and get the boundary conditions needed by the solver

    :param room_path: the path of the room model
    :param room: the room model
    """

    # todo, update model structure in roomparser
    def __init__(
        self,
        room_path: Path = Path(""),
        room: Room = None,
    ) -> None:
        # boundary conditions
        self._crac_setpoints_dict = {}
        self._crac_volume_flow_rates_dict = {}
        self._server_load_dict = {}
        self._server_flow_rate_dict = {}
        # sensor temperature
        self._sensor_temp_dict = {}
        # server type model
        self._server_type_dict = {}
        self._server_type_list = []
        self._load_room_model(room_path, room)
        self._load_server_type()

    def _load_room_model(
        self,
        room_path: Path = Path(""),
        room: Room = None,
    ) -> None:
        if Path(room_path) != Path("") and Path(room_path).absolute().exists():
            self.model = Room.load(file_path=room_path)
        elif room is not None:
            self.model = room
        else:
            raise ValueError("Either room_path or room must be provided.")

    def _load_server_type(self) -> None:
        for rack_key, rack in self.model.constructions.racks.items():
            for server_key, server in rack.constructions.servers.items():
                if server.geometry.model is not None:
                    self._server_type_dict[server_key] = server.geometry.model
                    if server.geometry.model not in self._server_type_list:
                        self._server_type_list.append(server.geometry.model)
                else:
                    logger.warning(f"server {server_key} type is not defined")

    @property
    def num_crac(self) -> int:
        return len(self.model.objects.acus.items())

    @property
    def num_ser(self) -> int:
        return len(self.model.objects.servers.items())

    @property
    def num_sen(self) -> int:
        return len(self.model.objects.sensors.items())

    @property
    def crac_list(self) -> list:
        return list(self.model.objects.acus.keys())

    @property
    def ser_list(self) -> List:
        return list(self.model.objects.servers.keys())

    @property
    def rack_list(self) -> List:
        return list(self.model.objects.racks.keys())

    @property
    def sen_list(self) -> List:
        return list(self.model.objects.sensors.keys())

    @property
    def server_type_list(self) -> List:
        return self._server_type_list

    @property
    def server_type_dict(self) -> Dict:
        return self._server_type_dict

    @property
    def acu_temp_array(self) -> np.ndarray:
        return np.asarray(list(self._crac_setpoints_dict.values()))

    @property
    def acu_flow_array(self) -> np.ndarray:
        return np.asarray(list(self._crac_volume_flow_rates_dict.values()))

    @property
    def ser_load_array(self) -> np.ndarray:
        return np.asarray(list(self._server_load_dict.values()))

    @property
    def acu2sen(self) -> np.ndarray:
        """ Get the distance matrix of the ACU to sensor connections
        """
        acu2sen_dis = np.zeros([self.num_crac, self.num_sen])
        for acu_idx, acu in enumerate(self.model.objects.acus.values()):
            for sen_idx, sen_loc in enumerate(self.model.probes):
                acu_loc = acu.placement
                acu2sen_dis[acu_idx][sen_idx] = self.euclidean_distance(acu_loc, sen_loc)
        return acu2sen_dis

    @property
    def ser2sen(self) -> np.ndarray:
        """ Get the distance matrix of the server to sensor connections
        """
        ser2sen_dis = np.zeros([self.num_ser, self.num_sen])
        for ser_idx, ser in enumerate(self.model.objects.servers.values()):
            for sen_idx, sen_loc in enumerate(self.model.probes):
                ser_loc_i, ser_loc_o = self.model.server_patch_positions(ser.id)
                ser2sen_dis[ser_idx][sen_idx] = self.euclidean_distance(ser_loc_o, sen_loc)
        return ser2sen_dis

    @property
    def acu2ser(self) -> np.ndarray:
        """ Get the distance matrix of the acu to server connections
        """
        acu2ser_dis = np.zeros([self.num_crac, self.num_ser])
        for acu_idx, acu in enumerate(self.model.objects.acus.values()):
            for ser_idx, ser in enumerate(self.model.objects.servers.values()):
                acu_loc = acu.placement
                ser_loc, _ = self.model.server_patch_positions(ser.id)
                acu2ser_dis[acu_idx][ser_idx] = self.euclidean_distance(acu_loc, ser_loc)
        return acu2ser_dis

    @staticmethod
    def euclidean_distance(loc_1: Vertex, loc_2: Vertex) -> float:
        return math.sqrt((loc_1.x - loc_2.x) ** 2 + (loc_1.y - loc_2.y) ** 2 + (loc_1.z - loc_2.z) ** 2)

    def _update_crac_boundary(
        self,
        crac_setpoints: Dict,
        crac_volume_flow_rates: Dict,
    ) -> None:
        for uid, prop in self.model.objects.acus.items():
            if crac_setpoints is not None:
                try:
                    prop.supply_temperature = crac_setpoints[uid]
                    self._crac_setpoints_dict[uid] = crac_setpoints[uid]
                except KeyError:
                    logger.critical(
                        f"CRAC {uid} setpoint is missing"
                    )
            if crac_volume_flow_rates is not None:
                try:
                    prop.flow_rate = crac_volume_flow_rates[uid]
                    self._crac_volume_flow_rates_dict[uid] = crac_volume_flow_rates[uid]
                except KeyError:
                    logger.critical(
                        f"CRAC {uid} volume flow rate is missing"
                    )

    def _update_server_boundary(
        self,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
    ) -> None:
        for uid, prop in self.model.objects.servers.items():
            if server_powers is not None:
                try:
                    prop.heat_load = server_powers[uid]
                    self._server_load_dict[uid] = server_powers[uid]
                except KeyError:
                    logger.critical(f"server {uid} power is missing")
            if server_volume_flow_rates is not None:
                try:
                    prop.flow_rate = server_volume_flow_rates[uid]
                    self._server_flow_rate_dict[uid] = server_volume_flow_rates[uid]
                except KeyError:
                    logger.critical(f"server {uid} volume flow rate is missing")

    def update_boundary_conditions(
        self,
        crac_setpoints: Dict = None,
        crac_volume_flow_rates: Dict = None,
        server_powers: Dict = None,
        server_volume_flow_rates: Dict = None,
    ) -> None:
        self._update_crac_boundary(crac_setpoints, crac_volume_flow_rates)
        self._update_server_boundary(server_powers, server_volume_flow_rates)

    @property
    def format_boundary_conditions(self) -> Dict:
        boundary_conditions = {
            "crac_setpoints": {}, "crac_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
        }
        for uid, prop in self.model.objects.servers.items():
            boundary_conditions["server_powers"][uid] = prop.heat_load
            boundary_conditions["server_volume_flow_rates"][uid] = prop.flow_rate
        for uid, prop in self.model.objects.acus.items():
            boundary_conditions["crac_setpoints"][uid] = prop.supply_temperature
            boundary_conditions["crac_volume_flow_rates"][uid] = prop.flow_rate

        return boundary_conditions
