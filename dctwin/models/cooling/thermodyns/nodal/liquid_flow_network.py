import torch
import torch.nn as nn

from typing import Dict, Tuple

from dclib.cooling.room.facilities import CDU

from dctwin.utils.const import water_specific_heat


class FlowNetwork(nn.Module):

    def __init__(
        self,
        cdu: CDU
    ):
        super(FlowNetwork, self).__init__()
        self.cdu = cdu


    def _sim_servers(
        self,
        server_power: torch.Tensor,
        inlet_liquid_temperature: torch.Tensor,
        inlet_liquid_mass_flow_rate: torch.Tensor,
        liquid_cooling_percentage: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Simulate the server friction power due to the liquid cooling pipes installed in the chips.
        """
        liquid_cooled_power = server_power * liquid_cooling_percentage
        # server total power
        liquid_outlet_temperature = inlet_liquid_temperature + liquid_cooled_power / (
            water_specific_heat * inlet_liquid_mass_flow_rate
        )
        # empirical formula for the maximum temperature of the CPU based on chip-level CFD simulation
        cpu_max_temperature = (
            1.04 * inlet_liquid_temperature +
            1.44 * server_power * 0.0016 / (inlet_liquid_mass_flow_rate * water_specific_heat)
        )
        return liquid_outlet_temperature, cpu_max_temperature, liquid_cooled_power

    def forward(
        self,
        server_powers: Dict[str, torch.Tensor],
        inlet_liquid_mass_flow_rates: Dict[str, torch.Tensor],
        liquid_cooling_percentages: Dict[str, torch.Tensor],
        inlet_liquid_temperature: torch.Tensor
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str,torch.Tensor], torch.Tensor, torch.Tensor, torch.Tensor]:

        liquid_outlet_temperatures = {}
        chip_max_temperatures = {}
        cdu_return_temperature = torch.zeros(1,)
        cdu_total_mass_flow_rate = torch.zeros(1,)
        cdu_total_liquid_cooled_power = torch.zeros(1,)
        for server_name, server in self.cdu.constructions.connected_servers.items():
            liquid_outlet_temperature, chip_max_temperature, liquid_cooled_power = self._sim_servers(
                server_power=server_powers[server_name],
                inlet_liquid_temperature=inlet_liquid_temperature,
                inlet_liquid_mass_flow_rate=inlet_liquid_mass_flow_rates[server_name],
                liquid_cooling_percentage=liquid_cooling_percentages[server_name]
            )
            liquid_outlet_temperatures[server_name] = liquid_outlet_temperature
            chip_max_temperatures[server_name] = chip_max_temperature
            cdu_return_temperature += liquid_outlet_temperature * inlet_liquid_mass_flow_rates[server_name]
            cdu_total_mass_flow_rate += inlet_liquid_mass_flow_rates[server_name]
            cdu_total_liquid_cooled_power += liquid_cooled_power

        # compute the cdu return temperature as weighted average of all server outlet temperature
        cdu_return_temperature /= cdu_total_mass_flow_rate

        return (
            liquid_outlet_temperatures,
            chip_max_temperatures,
            cdu_return_temperature,
            cdu_total_mass_flow_rate,
            cdu_total_liquid_cooled_power
        )