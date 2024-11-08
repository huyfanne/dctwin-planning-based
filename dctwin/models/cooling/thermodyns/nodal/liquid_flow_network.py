import torch
import torch.nn as nn

from typing import Dict, Any

from dclib.cooling.room.liquid_loops import LiquidFlowLoops

from dctwin.data import Batch
from dctwin.models.cooling.facilities import PumpModel
from dctwin.models.computing.d2c_server import D2CServerModel


class FlowNetwork(nn.Module):

    def __init__(
        self,
        liquid_flow_loop: LiquidFlowLoops,
        key_mapping: dict,
        learnable: bool = True,
        device: str | int | torch.device = "cpu",
    ) -> None:
        super(FlowNetwork, self).__init__()
        self.liquid_flow_loop = liquid_flow_loop
        self.key_mapping = key_mapping
        self.learnable = learnable
        self.device = device
        self.num_servers = 0
        self.models = self._init_models()

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the liquid loop equipments,
        including the CDUs and liquid network
        """
        for supply_branch_name, supply_branch in self.liquid_flow_loop.supply_branches.items():
            if supply_branch.components.cdus is not None:
                for cdu_name, cdu in supply_branch.components.cdus.items():
                    self.add_module(
                        name=f"{cdu_name} pump",
                        module=PumpModel(
                            config=cdu.constructions.pump,
                            key_mapping=self.key_mapping,
                            learnable=self.learnable,
                            device=self.device
                        )
                    )
        for demand_branch_name, demand_branch in self.liquid_flow_loop.demand_branches.items():
            if demand_branch.components.servers is not None:
                for server_name, server in demand_branch.components.servers.items():
                    self.add_module(
                        name=server_name,
                        module=D2CServerModel(
                            config=server,
                            key_mapping=self.key_mapping,
                            learnable=self.learnable,
                            device=self.device
                        )
                    )
                    self.num_servers += 1
        return {k: v for k, v in dict(self.named_modules()).items() if k != "" and "." not in k}

    def forward(
        self,
        data: Batch,
        zone_name: str
    ) -> None:
        # compute the total mass flow rate supplied by the CDUs
        cdu_total_mass_flow_rate = torch.zeros(1, )
        cdu_supply_temperature = torch.zeros(1, )
        for supply_branch_name, supply_branch in self.liquid_flow_loop.supply_branches.items():
            if supply_branch.components.cdus is not None:
                for cdu_name, cdu in supply_branch.components.cdus.items():
                    cdu_total_mass_flow_rate += data.acts[cdu_name].supply_mass_flow_rate_sp
                    cdu_supply_temperature += (
                        data.acts[cdu_name].supply_temperature_sp * data.acts[cdu_name].supply_mass_flow_rate_sp
                    )
                    cdu_pump_power = self.models[f"{cdu_name} pump"].forward(
                        mass_flow_rate=data.acts[cdu_name].supply_mass_flow_rate_sp
                    )
                    data.obs_next.zones[cdu_name].electrical_power = cdu_pump_power
                    data.obs_next.zones[cdu_name].cooling_water_supply_temperature = (
                        data.acts[cdu_name].supply_temperature_sp
                    )
                    data.obs_next.zones[cdu_name].cooling_water_mass_flow_rate = (
                        data.acts[cdu_name].supply_mass_flow_rate_sp
                    )
        cdu_supply_temperature /= cdu_total_mass_flow_rate

        # simulate liquid loop demand side: simulate the cold-plate inside the servers
        total_sensible_heat_load = torch.zeros(1,)
        cdu_return_temperature = torch.zeros(1,)
        for demand_branch_name, demand_branch in self.liquid_flow_loop.demand_branches.items():
            if demand_branch.components.servers is not None:
                for server_name, server in demand_branch.components.servers.items():
                    data.obs_next.zones[server_name].liquid_inlet_temperature = cdu_supply_temperature
                    data.obs_next.zones[server_name].power = data.inps[server_name]
                    data.obs_next.dc.total_ite_demand_power += data.inps[server_name]
                    liquid_outlet_temperature, max_chip_temperature, liquid_cooled_power =\
                        self.models[server_name].forward(
                            server_power=data.inps[server_name],
                            inlet_liquid_temperature=cdu_supply_temperature,
                            inlet_liquid_mass_flow_rate=cdu_total_mass_flow_rate / self.num_servers,
                            # liquid_cooling_percentage=torch.tensor([1.0], dtype=torch.float32)
                        )
                    total_sensible_heat_load += (
                        data.inps[server_name] - liquid_cooled_power
                    )
                    data.obs_next.zones[server_name].liquid_outlet_temperature = liquid_outlet_temperature
                    data.obs_next.zones[server_name].max_chip_temperature = max_chip_temperature
                    cdu_return_temperature += liquid_outlet_temperature
        # compute the sensible heat load of the zone that should be removed by the air loop
        data.obs_next.zones[zone_name].sensible_heat_load = total_sensible_heat_load

        for supply_branch_name, supply_branch in self.liquid_flow_loop.supply_branches.items():
            if supply_branch.components.cdus is not None:
                for cdu_name, cdu in supply_branch.components.cdus.items():
                    data.obs_next.zones[cdu_name].cooling_water_return_temperature =\
                        cdu_return_temperature / self.num_servers
