from typing import Dict, Optional, Any
from dclib import Room
import torch.nn as nn
import torch

from dctwin.data import Batch
from dctwin.models.cooling.facilities.pump import CDUPump
from dctwin.models.cooling.thermodyns.nodal.liquid_flow_network import FlowNetwork


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
        self.models = self._init_models()

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the liquid loop equipments,
        including the CDUs and liquid network
        """
        zone_flow_network_models = {}
        for zone_name, zone in self.zones.items():
            zone_flow_network_models[zone_name] = FlowNetwork()
            self.add_module(zone_name, zone_flow_network_models[zone_name])
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    # search for the racks that are under the control of the current CDU
                    racks = {}
                    for rack_name in cdu.meta.racks:
                        racks[rack_name] = zone.constructions.racks[rack_name]
                    cdu.model = CDUPump(cdu.constructions.pump)
                    self.add_module(cdu_name, cdu.model)
                    zone_flow_network_models[zone_name][cdu_name] = cdu.model
        return zone_flow_network_models

    def learn(self) -> None:
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for zone_name, zone_cdus in self.cdus.items():
            for cdu_name, cdu in zone_cdus.items():
                cdu.learn()

    def collect(self, data: Batch | Dict) -> None:
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
    ) -> None:
        for zone_name, zone_cdus in self.cdus.items():
            for cdu_name, cdu in zone_cdus.items():
                current_server_powers = {}
                server_mass_flow_rates = {}
                current_server_liquid_cooling_percentages = {}
                # solve demand side of the liquid cooling network
                for rack_name, rack in cdu.racks.items():
                    for server_name, server in rack.constructions.servers.items():
                        current_server_powers[server_name] = data.obs_next.zones[zone_name].sensible_heat_load
                        server_mass_flow_rates[server_name] = data.acts[cdu_name].supply_mass_flow_rate_sp
                        current_server_liquid_cooling_percentages[server_name] = torch.tensor([1.0], dtype=torch.float32)
                # simulate the supply side liquid flow network
                cooling_water_supply_temperature = data.acts[cdu_name].supply_temperature_sp
                (
                    total_friction_power,
                    cdu_return_temperature,
                ) = self.models[zone_name].forward(
                    server_powers=current_server_powers,
                    server_mass_flow_rates=server_mass_flow_rates,
                    server_liquid_cooling_percentages=current_server_liquid_cooling_percentages,
                    cooling_water_supply_temperature=cooling_water_supply_temperature,
                )
                cooling_water_mass_flow_rate = torch.tensor(list(server_mass_flow_rates.values())).sum()
                cdu_pump_power = self.cdu.model.forward(total_friction_power)
                # update cdu simulation results
                data.obs_next.zone[cdu_name].cdu_electrical_power = cdu_pump_power
                data.obs_next.zone[cdu_name].cooling_water_supply_temperature = cooling_water_supply_temperature
                data.obs_next.zone[cdu_name].cdu_return_temperature = cdu_return_temperature
                data.obs_next.zone[cdu_name].cooling_water_mass_flow_rate = cooling_water_mass_flow_rate
