import torch
import torch.nn as nn

from dctwin.utils.const import air_specific_heat


class SteadyStateThermodynamics(nn.Module):

    def __init__(self):
        super(SteadyStateThermodynamics, self).__init__()

    def forward(
        self,
        supply_air_temperature: torch.Tensor,
        supply_air_mass_flow_rate: torch.Tensor,
        sensible_heat_load: torch.Tensor,
    ) -> torch.Tensor:
        """
        Simulate the steady-state return air temperature of the ACU
        :param supply_air_temperature: the supply air temperature of the ACU
        :param supply_air_mass_flow_rate: the supply air mass flow rate of the ACU
        :param sensible_heat_load: the sensible heat load of the ACU
        :return: the return air temperature of the ACU
        """
        return supply_air_temperature + sensible_heat_load / (
                air_specific_heat * supply_air_mass_flow_rate
        )
