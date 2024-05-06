from typing import Tuple

import torch
import torch.nn as nn

from dclib.ite.composite import ITE

from dctwin.models.curves import BiQuadraticCurve, QuadraticCurve


class ITEModel(nn.Module):
    """
    Implement the learnable ITE model. The model can take the CPU loading workloads and inlet air temperature as input
    and output the power consumption of the CPU, Fan and UPS.
    """
    def __init__(
        self, config: ITE, learnable: bool = False
    ):
        super(ITEModel, self).__init__()
        self.config = config
        self.name = config.uid
        self.zone = config.zone
        # define the model parameters
        self.fan_power_curve = QuadraticCurve(
            init_params=torch.tensor(config.fan_power_input_function_of_flow_curve, dtype=torch.float32),
            requires_grad=learnable
        )
        self.cpu_power_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.cpu_power_input_function_of_loading_and_air_temperature_curve, dtype=torch.float32
            ),
            requires_grad=learnable
        )
        self.recirculation_fraction_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.recirculation_fraction_function_of_loading_and_air_temperature_curve, dtype=torch.float32
            ),
            requires_grad=learnable
        )
        self.electric_power_supply_efficiency_curve = QuadraticCurve(
            init_params=torch.tensor(
                config.electric_power_supply_efficiency_function_of_part_load_ratio_curve, dtype=torch.float32
            ),
            requires_grad=learnable
        )
        self.air_flow_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.air_flow_function_of_loading_and_air_temperature_curve, dtype=torch.float32
            ),
            requires_grad=learnable
        )

    def forward(
        self,
        cpu_schedule: torch.Tensor,
        inlet_air_temperature: torch.Tensor = None
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if inlet_air_temperature is None:
            inlet_air_temperature = torch.tensor(
                0, dtype=torch.float32
            ).view(-1, 1)
        # calculate the cpu power
        cpu_power = (
            self.cpu_power_curve(cpu_schedule, inlet_air_temperature) * self.config.rated_power *
            (1 - self.config.design_fan_power_input_fraction)
        )
        # calculate server fan flow rate
        fan_flow_rate = self.air_flow_curve(cpu_schedule, inlet_air_temperature)
        # calculate fan power
        fan_power = (
            self.fan_power_curve(fan_flow_rate) * self.config.rated_power * self.config.design_fan_power_input_fraction
        )
        # calculate the power loss of the UPS
        ups_heat_load = (cpu_power + fan_power) * (1 - self.config.design_electric_power_supply_efficiency)
        return cpu_power + fan_power + ups_heat_load

    def collect(self, data: dict):
        pass

    def learn(self):
        pass
