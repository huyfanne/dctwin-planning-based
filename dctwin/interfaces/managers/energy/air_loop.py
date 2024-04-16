from pathlib import Path
from typing import Dict

import torch
import torch.nn as nn

from dclib.room import Room

from dcdyn.models.devices import FanModel
from dcdyn.data import Batch
from dcdyn.models.thermodyn import SteadyStateThermodynamics


class AirLoopManager(nn.Module):
    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Dict,
    ):
        super(AirLoopManager, self).__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.zone_air_temperatures = {}
        self.models = self._init_models()
        self.thermodynamics_model = SteadyStateThermodynamics()

    def _init_models(self):
        """
        Initialize the learnable models for the zone equipments
        """
        zone_models = {}
        # get the model for each zone equipment of the building
        for zone_name, zone in self.zones.items():
            zone_models[zone_name] = {}
            # get the ACU equipments of the zone
            for acu_name, acu in zone.constructions.acus.items():
                # get the model of the ACU
                zone_models[zone_name][acu.uid] = FanModel(
                    config=acu,
                    key_mapping=self.device_key_mapping["acus"][acu_name]["fan"]
                )
                self.add_module(acu_name, zone_models[zone_name][acu.uid])
        return zone_models

    def _sim(
        self,
        heat_loads: Batch,
        acu_controls: Batch,
    ):
        # Simulate the ITEs in each zone
        acu_property = Batch(
            air_mass_flow_rates=Batch(),
            return_air_temperatures=Batch(),
            fan_powers=Batch(),
        )
        zone_temperatures = Batch()
        for zone_name, zone_model in self.models.items():
            # calculate total zone heat gain
            zone_total_heat_load = heat_loads[zone_name]
            # simulate the load distribution among multiple ACUs in each zone
            num_acus = len(zone_model)
            off_acu_name = []
            zone_acu_heat_load = {acu_name: zone_total_heat_load / num_acus for acu_name in zone_model}
            return_temperature = 0
            for acu_name, acu in zone_model.items():
                acu_property.air_mass_flow_rates[acu.uid] = acu_controls[acu.uid].supply_air_mass_flow_rate
                acu_property.fan_powers[acu.uid] = zone_model[acu.uid](
                    acu_controls[acu.uid].supply_air_mass_flow_rate
                )
                # simulate the return air temperature of the ACU
                if torch.isclose(acu_controls[acu.uid].supply_air_mass_flow_rate, torch.zeros(1)):
                    num_acus -= 1
                    off_acu_name.append(acu_name)
                else:
                    return_temperature += SteadyStateThermodynamics.sim(
                        supply_air_temperature=acu_controls[acu.uid].supply_air_temperature,
                        supply_air_mass_flow_rate=acu_controls[acu.uid].supply_air_mass_flow_rate,
                        sensible_heat_load=zone_acu_heat_load[acu.uid],
                    )
            # calculate the zone temperature
            zone_temperatures[zone_name] = return_temperature / num_acus
            for acu_name, acu in zone_model.items():
                acu_property.return_air_temperatures[acu.uid] = zone_temperatures[zone_name]
            # update the zone air temperature
            self.zone_air_temperatures[zone_name] = zone_temperatures[zone_name]
        return acu_property, zone_temperatures

    def collect(self, data: dict):
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
        heat_loads: Batch,
        acu_controls: Batch
    ):
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        acu_property, zone_temperatures = self._sim(
            heat_loads=heat_loads,
            acu_controls=acu_controls
        )
        return Batch(
            acu_property=acu_property,
            zone_temperatures=zone_temperatures,
        )

    def save(
        self, save_path: Path
    ):
        # save the zone equipment models
        for zone_name, zone_models in self.models.items():
            # save the acu fan performance model
            for fan_name, fan_model in zone_models["fans"].items():
                fan_model.save(save_path / f"{zone_name}_{fan_name}.pt")
