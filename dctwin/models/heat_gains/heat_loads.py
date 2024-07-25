from typing import Dict
import torch
import torch.nn as nn

from dclib.room import Room

from dctwin.models.heat_gains.ite import ITEModel
from dctwin.data import Batch


class HeatLoadManager(nn.Module):
    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Dict
    ):
        super(HeatLoadManager, self).__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.models = self._init_models()

    def _init_models(self):
        """
        Initialize the learnable models for the zone equipments
        """
        zone_models = {
            "ites": {},
        }
        # get the model for each zone equipment of the building
        for zone_name, zone in self.zones.items():
            # get the ITE equipments of the zone
            for ite_name, ite in zone.constructions.heat_gains.ites.items():
                # get the model of the ITE
                zone_models["ites"][ite.uid.lower()] = ITEModel(ite)
                self.add_module(ite.uid, zone_models["ites"][ite.uid.lower()])
        return zone_models

    def _sim_zone_ite_heat_gains(
        self, zone_cpu_load_schedules: Batch
    ):
        ite_heat_load = 0.0
        for ite_name, cpu_load_schedule in zone_cpu_load_schedules.items():
            ite_heat_load += self.models["ites"][ite_name.lower()](
                cpu_load_schedule,
                None
            )
        return ite_heat_load

    def collect(self, data: dict):
        pass

    def learn(self):
        pass

    def forward(
        self,
        states: Batch,
        actions: Batch
    ):
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        for zone_name, zone in self.zones.items():
            total_ite = 0.
            total_ite = torch.zeros(1,)
            for ite_name, ite in zone.constructions.heat_gains.ites.items():
                total_ite += self.models["ites"][ite.uid.lower()](
                    actions[ite_name].cpu_load_utilization,
                    None
                )
            states[zone_name].sensible_heat_load = total_ite
