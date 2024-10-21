from typing import Dict, Any

import torch.nn as nn

import torch
from dclib.room import Room

from dctwin.models.cooling.facilities import FanModel
from dctwin.models.cooling.thermodyns import SteadyStateThermodynamics
from dctwin.data import Batch


class AirLoopManager(nn.Module):

    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Dict,
        time_step: float = None,
    ) -> None:
        super().__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.time_step = time_step
        self.models = self._init_models()

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the zone equipments
        """
        # get the model for each zone equipment of the building
        for zone_name, zone in self.zones.items():
            self.add_module(
                f"{zone_name} thermodynamics",
                SteadyStateThermodynamics()
            )
            # get the ACU equipments of the zone
            for acu_name, acu in zone.constructions.acus.items():
                self.add_module(
                    f"{acu_name} fan",
                    FanModel(
                        config=acu,
                        key_mapping=self.device_key_mapping["acus"][acu_name]["fan"],
                    )
                )
        return {k: v for k, v in dict(self.named_modules()).items() if k is not "" and "." not in k}

    def collect(self, data: Batch | Dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        # feed online data to the zone equipment models
        for zone_name, zone_models in self.models.items():
            for fan_name, fan_model in zone_models.items():
                fan_model.collect(data)

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for zone_name, zone_models in self.models.items():
            # learn the acu fan performance model
            for fan_name, fan_model in zone_models.items():
                fan_model.learn()

    def forward(
        self,
        data: Batch
    ) -> None:
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        for zone_name, zone in self.zones.items():
            # get the active acu ids
            active_acu_ids = [
                acu_name for acu_name, acu in zone.constructions.acus.items() if data.acts[acu_name].on_off_schedule == 1
            ]
            # uniform distribution of the heat load among active ACUs
            zone_acu_heat_load = {
                active_acu_name: data.obs_next.zones[zone_name].sensible_heat_load / len(active_acu_ids)
                for active_acu_name in active_acu_ids

            }
            weighted_return_temperature = torch.zeros(1,)
            total_acu_air_mass_flow_rate = torch.zeros(1,)
            for acu_name, acu in zone.constructions.acus.items():
                if acu_name in active_acu_ids:
                    data.obs_next.zones[acu_name].supply_air_mass_flow_rate =\
                        data.acts[acu_name].supply_mass_flow_rate_sp
                    data.obs_next.zones[acu_name].supply_air_temperature =\
                        data.acts[acu_name].supply_temperature_sp
                    data.obs_next.zones[acu_name].fan_power = self.models[f"{acu_name} fan"](
                        data.acts[acu_name].supply_mass_flow_rate_sp
                    )
                    acu_return_temperature = self.models[f"{zone_name} thermodynamics"].forward(
                        supply_air_temperature=data.acts[acu_name].supply_temperature_sp,
                        supply_air_mass_flow_rate=data.acts[acu_name].supply_mass_flow_rate_sp,
                        sensible_heat_load=zone_acu_heat_load[acu_name],
                    )
                    data.obs_next.zones[acu_name].return_air_temperature = acu_return_temperature
                    weighted_return_temperature += (
                        acu_return_temperature * data.acts[acu_name].supply_mass_flow_rate_sp
                    )
                    total_acu_air_mass_flow_rate += data.acts[acu_name].supply_mass_flow_rate_sp

            # update the zone air temperature
            data.obs_next.zones[zone_name].zone_air_temperature = (
                weighted_return_temperature / total_acu_air_mass_flow_rate
            )
            # TODO: update zone humidity
            # TODO: calculate the zone ITE inlet temperature
