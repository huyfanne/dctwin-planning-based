from typing import Dict, Optional, Any
from dclib import Room
import torch.nn as nn
import torch

from dctwin.data import Batch
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
            if zone.constructions.liquid_flow_networks is not None:
                for liquid_network_name, liquid_network in zone.constructions.liquid_flow_networks.items():
                    self.add_module(
                        name=liquid_network_name,
                        module=FlowNetwork(
                            liquid_network=liquid_network,
                            key_mapping=self.device_key_mapping,
                            learnable=True
                        )
                    )
        return {k: v for k, v in dict(self.named_modules()).items() if k != "" and "." not in k}

    def learn(self) -> None:
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for model_name, model in self.models.items():
            model.learn()

    def collect(self, data: Batch | Dict) -> None:
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        for model_name, model in self.models.items():
            model.collect(data)

    def forward(
        self,
        data: Batch
    ) -> None:
        for zone_name, zone in self.zones.items():
            zone_cdu_liquid_cooled_power = torch.zeros(1,)
            num_servers = 0
            if zone.constructions.liquid_flow_networks is None:
                continue
            for liquid_flow_networks_name, liquid_flow_network in zone.constructions.liquid_flow_networks.items():
                # compute the total mass flow rate supplied by the CDUs
                cdu_total_mass_flow_rate = torch.zeros(1,)
                cdu_supply_temperature = torch.zeros(1,)
                for supply_branch_name, supply_branch in liquid_flow_network.supply_branches.items():
                    if supply_branch.components.cdus is not None:
                        for cdu_name, cdu in supply_branch.components.cdus.items():
                            cdu_total_mass_flow_rate += data.acts[cdu_name].supply_mass_flow_rate_sp
                            cdu_supply_temperature += (
                                data.acts[cdu_name].supply_temperature_sp * data.acts[cdu_name].supply_mass_flow_rate_sp
                            )
                            # cdu_pump_power = self.models[liquid_flow_networks_name]
                            # data.obs_next.zones[cdu_name].electrical_power = cdu_pump_power
                            data.obs_next.zones[cdu_name].cooling_water_supply_temperature = (
                                data.acts[cdu_name].supply_temperature_sp
                            )
                            data.obs_next.zones[cdu_name].cooling_water_mass_flow_rate = (
                                data.acts[cdu_name].supply_mass_flow_rate_sp
                            )
                cdu_supply_temperature /= cdu_total_mass_flow_rate
                # compute server power, mass flow rate, and liquid cooling percentage
                server_powers = {}
                server_mass_flow_rates = {}
                server_liquid_cooling_percentages = {}
                for demand_branch_name, demand_branch in liquid_flow_network.demand_branches.items():
                    if demand_branch.components.servers is not None:
                        for server_name, server in demand_branch.components.servers.items():
                            num_servers += 1
                for demand_branch_name, demand_branch in liquid_flow_network.demand_branches.items():
                    if demand_branch.components.servers is not None:
                        for server_name, server in demand_branch.components.servers.items():
                            server_powers[server_name] = (
                                data.obs_next.zones[zone_name].sensible_heat_load / num_servers
                            )
                            server_mass_flow_rates[server_name] = (
                                cdu_total_mass_flow_rate / num_servers
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
                ) = self.models[liquid_flow_networks_name].forward(
                    server_powers=server_powers,
                    inlet_liquid_mass_flow_rates=server_mass_flow_rates,
                    inlet_liquid_temperature=cdu_supply_temperature,
                    liquid_cooling_percentages=server_liquid_cooling_percentages,
                )
                # update cdu simulation results
                for supply_branch_name, supply_branch in liquid_flow_network.supply_branches.items():
                    if supply_branch.components.cdus is not None:
                        for cdu_name, cdu in supply_branch.components.cdus.items():
                            data.obs_next.zones[cdu_name].cooling_water_return_temperature = cdu_return_temperature
                zone_cdu_liquid_cooled_power += cdu_liquid_cooled_power
            # deduct zone sensible heat load from liquid cooled
            data.obs_next.zones[zone_name].sensible_heat_load -= zone_cdu_liquid_cooled_power
