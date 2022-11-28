import numpy as np
from typing import Dict, List
from pathlib import Path
from dctwin.models import Room

from loguru import logger


class RoomParser:
    """
    A class to parse the room model and get the boundary conditions needed by the solver

    :param room_path: the path of the room model
    :param room: the room model
    """
    def __init__(
        self,
        room_path: Path = Path(""),
        room: Room = None
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
        for key, prop in self.model.objects.servers.items():
            if prop.model is not None:
                self._server_type_dict[prop.id] = prop.model
                if prop.model not in self._server_type_list:
                    self._server_type_list.append(prop.model)
            else:
                logger.warning(f"server {prop.id} type is not defined")

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

    def _update_crac_boundary(
        self,
        crac_setpoints: Dict,
        crac_volume_flow_rates: Dict,
    ) -> None:
        for uid, prop in self.model.objects.acus.items():
            try:
                prop.supply_temperature = crac_setpoints[uid]
                self._crac_setpoints_dict[uid] = crac_setpoints[uid]
            except KeyError:
                logger.warning(f"CRAC {uid} setpoint is missing, set to 0")
                prop.supply_temperature = 0
                self._crac_setpoints_dict[uid] = 0 # that means the CRAC is off
            try:
                prop.flow_rate = crac_volume_flow_rates[uid]
                self._crac_volume_flow_rates_dict[uid] = crac_volume_flow_rates[uid]
            except KeyError:
                logger.warning(f"CRAC {uid} volume flow rate is missing, set to 0")
                prop.flow_rate = 0
                self._crac_volume_flow_rates_dict[uid] = 0 # avoid zero division error

    def _update_server_boundary(
        self,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
    ) -> None:
        for uid, prop in self.model.objects.servers.items():
            try:
                prop.heat_load = server_powers[uid]
                self._server_load_dict[uid] = server_powers[uid]
            except KeyError:
                logger.warning(f"server {uid} power is missing, set to 0")
                prop.heat_load = 0
                self._server_load_dict[uid] = 0
            if server_volume_flow_rates:
                try:
                    prop.flow_rate = server_volume_flow_rates[uid]
                    self._server_flow_rate_dict[uid] = server_volume_flow_rates[uid]
                except KeyError:
                    logger.warning(f"server {uid} volume flow rate is missing, set to 0")
                    prop.flow_rate = 1e-6
                    self._server_flow_rate_dict[uid] = 1e-6 # avoid zero division error

    def update_boundary_conditions(
        self,
        crac_setpoints: Dict,
        crac_volume_flow_rates: Dict,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
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
