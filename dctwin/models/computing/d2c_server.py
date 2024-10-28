from typing import Tuple
import torch
import torch.nn as nn

from dclib.ite.servers.server import Server
from dctwin.data import Buffer
from dctwin.utils.const import water_specific_heat


class D2CServerModel(nn.Module):
    """
    Implement the learnable chiller model. The model can take part load ratio as input and output the electric input.
    The power model is a quadratic function of the part load ratio which the parameters are learnable.
    """
    def __init__(
        self,
        config: Server,
        key_mapping: dict,
        learnable: bool = True,
        device: str | int | torch.device = "cpu",
    ) -> None:
        super(D2CServerModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        # define the replay buffer
        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping
        self.device = device

    def forward(
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

    def collect(self, data: dict):
        pass

    def learn(self):
        pass
