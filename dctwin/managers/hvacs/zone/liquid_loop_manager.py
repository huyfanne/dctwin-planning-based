from typing import Dict, Optional, Any
from dclib import Room
import torch.nn as nn
import torch

from dctwin.data import Batch
from dctwin.models.cooling.facilities.pump import PumpModel
from dctwin.models.cooling.thermodyns.nodal.liquid_flow_network import FlowNetwork


class LiquidLoopManager(nn.Module):
    """
    Implement the liquid cooling manager to simulate the thermal properties and the electrical power consumption
    of a hybrid cooling system with the direct-to-chip cooling system and conventional force ventilation air cooling
    system.
    """
    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Optional[Dict] = None
    ) -> None:
        super().__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.models = self._init_models()

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the liquid loop equipments,
        including the CDUs and liquid network
        """
        for zone_name, zone in self.zones.items():
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    self.add_module(
                        name=f"{cdu_name} flow network",
                        module=FlowNetwork(
                            cdu=cdu
                        )
                    )
                    self.add_module(
                        name=f"{cdu_name} pump",
                        module=PumpModel(
                            config=cdu.constructions.pump,
                            key_mapping=self.device_key_mapping,
                            learnable=True
                        )
                    )
        return {k: v for k, v in dict(self.named_modules()).items() if k is not ""}

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
        for zone_name, zone in self.zones.items():
            zone_cdu_liquid_cooled_power = torch.zeros(1,)
            num_servers = 0
            for cdu_name, cdu in zone.constructions.cdus.items():
                for server_name, server in cdu.constructions.connected_servers.items():
                    num_servers += 1
            for cdu_name, cdu in zone.constructions.cdus.items():
                server_powers = {}
                server_mass_flow_rates = {}
                server_liquid_cooling_percentages = {}
                # solve demand side of the liquid cooling network
                for server_name, server in cdu.constructions.connected_servers.items():
                    server_powers[server_name] = (
                        data.obs_next.zones[zone_name].sensible_heat_load / num_servers
                    )
                    server_mass_flow_rates[server_name] = (
                        data.acts[cdu_name].supply_mass_flow_rate_sp / num_servers
                    )
                    server_liquid_cooling_percentages[server_name] = torch.tensor(
                        [1.0], dtype=torch.float32
                    )
                # simulate the supply side liquid flow network
                (
                    liquid_outlet_temperatures,
                    chip_max_temperatures,
                    cdu_return_temperature,
                    cdu_mass_flow_rate,
                    cdu_liquid_cooled_power
                ) = self.models[f"{cdu_name} flow network"].forward(
                    server_powers=server_powers,
                    inlet_liquid_mass_flow_rates=server_mass_flow_rates,
                    inlet_liquid_temperature=data.acts[cdu_name].supply_temperature_sp,
                    liquid_cooling_percentages=server_liquid_cooling_percentages,
                )
                # simulate the pump power consumption given the total cooling water mass flow rate
                cdu_pump_power = self.models[f"{cdu_name} pump"].forward(data.acts[cdu_name].supply_mass_flow_rate_sp)
                # update cdu simulation results
                data.obs_next.zones[cdu_name].electrical_power = cdu_pump_power
                data.obs_next.zones[cdu_name].cooling_water_supply_temperature = data.acts[cdu_name].supply_temperature_sp
                data.obs_next.zones[cdu_name].cooling_water_return_temperature = cdu_return_temperature
                data.obs_next.zones[cdu_name].cooling_water_mass_flow_rate = cdu_mass_flow_rate
                zone_cdu_liquid_cooled_power += cdu_liquid_cooled_power
            # deduct zone sensible heat load from liquid cooled
            data.obs_next.zones[zone_name].sensible_heat_load -= zone_cdu_liquid_cooled_power
