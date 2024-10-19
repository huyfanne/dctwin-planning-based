from typing import Dict, Optional
from CoolProp.CoolProp import PropsSI
from dclib import Room
import torch.nn as nn

from dctwin.data import Batch
from dctwin.models.cooling.facilities.cdu import CDUModel


class LiquidLoopManager(nn.Module):
    """
    Implement the liquid cooling manager to simulate the thermal properties and the electrical power consumption
    of a hybrid cooling system with the direct-to-chip cooling system and conventional force ventilation air cooling
    system.
    """
    def __init__(
        self,
        rooms: Dict[str, Room],
        device_key_mapping: Optional[Dict] = None,
        fluid_name: str = 'water'
    ) -> None:
        super().__init__()
        self.zones = rooms
        self.device_key_mapping = device_key_mapping
        self.cdus = self._make_cdus()

    def _init_models(self):
        """
        Initialize the learnable models for the zone equipments
        """
        zone_cdu_models = {}
        # get the model for each zone equipment of the building
        for zone_name, zone in self.zones.items():
            zone_cdu_models[zone_name] = {}
            # get the ACU equipments of the zone
            for cdu_name, cdu in zone.constructions.cdus.items():
                cdu.model = CDUModel(
                    config=cdu,
                    key_mapping=self.device_key_mapping["acus"][acu_name]["fan"],
                )
                self.add_module(cdu_name, cdu.model)
                zone_cdu_models[zone_name][cdu_name] = cdu.model
        return zone_cdu_models

    def _make_cdus(self) -> Dict[str, Dict[str, CDUModel]]:
        """
        Create the CDU instances according to the room configuration.
        """
        cdus = {}
        for zone_name, zone in self.rooms.items():
            cdus[zone_name] = {}
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    # search for the racks that are under the control of the current CDU
                    racks = {}
                    for rack_name in cdu.meta.racks:
                        racks[rack_name] = zone.constructions.racks[rack_name]
                    cdus[zone_name][cdu_name] = CDUModel(
                        cdu=cdu,
                        racks=racks,
                    )
        return cdus

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for zone_name, zone_cdus in self.cdus.items():
            for cdu_name, cdu in zone_cdus.items():
                cdu.learn()

    def collect(self, data: Batch | Dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        # feed online data to the zone equipment models
        for zone_name, zone_cdus in self.cdus.items():
            for cdu_name, cdu in zone_cdus.items():
                cdu.collect(data)

    def forward(
        self,
        data: Batch
    ):
        for zone_name, zone_cdus in self.cdus.items():
            for cdu_name, cdu in zone_cdus.items():
                current_server_powers = {}
                current_server_mass_flow_rates = {}
                current_server_liquid_cooling_percentages = {}
                for rack_name, rack in cdu.racks.items():
                    for server_name, server in rack.constructions.servers.items():
                        current_server_powers[server_name] = data.obs_next.zones[zone_name].sensible_heat_load
                        current_server_mass_flow_rates[server_name] = data.acts[cdu_name].supply_mass_flow_rate_sp
                        current_server_liquid_cooling_percentages[server_name] = torch.tensor([1.0], dtype=torch.float32)
                # simulate the CDU
                cooling_water_supply_temperature = data.acts[cdu_name].supply_temperature_sp
                chilled_water_supply_temperature =\
                    data.obs.zone[zone_name].cdu[cdu_name].chilled_water_supply_temperature_sp
                (
                    cdu_electrical_power,
                    chilled_water_return_temperature,
                    cooling_water_supply_temperature,
                    cdu_return_temperature,
                    chilled_water_mass_flow_rate,
                    cooling_water_mass_flow_rate
                ) = cdu.forward(
                    server_powers=current_server_powers,
                    server_mass_flow_rates=current_server_mass_flow_rates,
                    server_liquid_cooling_percentages=current_server_liquid_cooling_percentages,
                    cooling_water_supply_temperature=cooling_water_supply_temperature,
                    chilled_water_supply_temperature=chilled_water_supply_temperature,
                )
                # update cdu simulation results
                data.obs_next.zone[cdu_name].cdu_electrical_power = cdu_electrical_power
                data.obs_next.zone[cdu_name].chilled_water_supply_temperature = chilled_water_supply_temperature
                data.obs_next.zone[cdu_name].chilled_water_return_temperature = chilled_water_return_temperature
                data.obs_next.zone[cdu_name].cooling_water_supply_temperature = cooling_water_supply_temperature
                data.obs_next.zone[cdu_name].cdu_return_temperature = cdu_return_temperature
                data.obs_next.zone[cdu_name].chilled_water_mass_flow_rate = chilled_water_mass_flow_rate
                data.obs_next.zone[cdu_name].cooling_water_mass_flow_rate = cooling_water_mass_flow_rate
