from typing import Dict
from pathlib import Path
from dctwin.models import Room


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
        if room_path != Path("") and room_path.exists():
            self.model = Room.load(file_path=room_path)
        elif room is not None:
            self.model = room
        else:
            raise ValueError("Either room_path or room must be provided.")

    @property
    def num_crac(self) -> int:
        return len(self.model.objects.acus.items())

    @property
    def num_ser(self) -> int:
        return len(self.model.objects.servers.items())

    @property
    def num_sen(self) -> int:
        return len(self.model.objects.sensors.items())

    def _update_crac_boundary(
        self,
        crac_setpoints: Dict,
        crac_flow_rates: Dict
    ) -> None:
        for uid, prop in self.model.objects.acus.items():
            prop.supply_temperature = crac_setpoints[uid]
            prop.flow_rate = crac_flow_rates[uid]

    def _update_server_boundary(
        self,
        server_powers: Dict,
        server_flow_rates: Dict
    ) -> None:
        for uid, prop in self.model.objects.servers.items():
            prop.heat_load = server_powers[uid]
            if server_flow_rates:
                prop.flow_rate = server_flow_rates[uid]

    def update_boundary_conditions(
        self,
        crac_setpoints: Dict,
        crac_volume_flow_rates: Dict,
        server_powers: Dict,
        server_volume_flow_rates: Dict
    ) -> None:
        self._update_crac_boundary(crac_setpoints, crac_volume_flow_rates)
        self._update_server_boundary(server_powers, server_volume_flow_rates)

    @property
    def format_boundary_conditions(self):
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
