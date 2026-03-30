import torch
from typing import Any, Tuple

from dclib import Building, Room

from dctwin.data import Batch


class ITEData:
    """
    The class to reset the Cloud computing system data for the environment, including zones and plant.
    """

    def __init__(self, model: Building):
        self._model = model

    @staticmethod
    def _reset_d2c_server_data(zone: Room, obs: dict, acts: dict) -> Tuple[dict, dict]:
        pass

    @staticmethod
    def _reset_acu_data(zone: Any, obs: dict, acts: dict) -> Tuple[dict, dict]:
        pass

    @staticmethod
    def _reset_cdu_data(zone: Room, obs: dict, acts: dict) -> Tuple[dict, dict]:
        pass

    @staticmethod
    def _reset_ite_data(zone: Any, zone_obs: dict, acts: dict) -> Tuple[dict, dict]:
        pass

    def reset_zone_data(self, obs: dict, acts: dict) -> Tuple[dict, dict]:
        for zone_name, zone in self._model.constructions.zones.items():
            obs[zone_name] = Batch(
                zone_air_temperature=torch.tensor(
                    zone.control_states.thermostats.cooling_setpoint,
                    dtype=torch.float32,
                    requires_grad=False,
                ),
                zone_air_relative_humidity=(),
                sensible_heat_load=(),
            )
            # reset zone facility and IT equipment data
            self._reset_d2c_server_data(zone, obs, acts)
            self._reset_acu_data(zone, obs, acts)
            self._reset_cdu_data(zone, obs, acts)
            self._reset_ite_data(zone, obs, acts)
        return obs, acts
