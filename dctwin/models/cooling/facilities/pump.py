import torch
import torch.nn as nn

from dclib.cooling.plant.facilities import Pump

from dcdyn.models.curves import CubicCurve

from ....data import Batch, Buffer
from ....utils.const import rho_water


class PumpModel(nn.Module):
    """
    Implement the learnable pump model. The model can take the mass flow rate as input and output the electric input.
    The power model is a quartic function of the mass flow rate which the parameters are learnable.
    """
    def __init__(
        self, config: Pump, key_mapping: dict, learnable: bool = True
    ):
        super(PumpModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable

        # define the model parameters
        self.power_curve = CubicCurve(
            init_params=torch.tensor([
                config.power.coefficient_1_of_the_part_load_performance_curve,
                config.power.coefficient_2_of_the_part_load_performance_curve,
                config.power.coefficient_3_of_the_part_load_performance_curve,
                config.power.coefficient_4_of_the_part_load_performance_curve,
            ], dtype=torch.float32),
            requires_grad=learnable
        )
        # initialize the replay buffer
        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping

    def collect(self, data: dict):
        assert "mass flow rate" in self.key_mapping.keys(), "The \"mass flow rate\" key is not provided."
        assert "power" in self.key_mapping.keys(), "The \"power\" key is not provided."
        assert self.key_mapping["mass flow rate"] in data.keys(),\
            f"{self.key_mapping['mass flow rate']} is not included in the data dictionary."
        assert self.key_mapping["power"] in data.keys(),\
            f"{self.key_mapping['power']} is not included in the data dictionary."
        self.buffer.add(
            Batch(
                pump_mass_flow_rate=data[self.key_mapping["mass flow rate"]],
                pump_power=data[self.key_mapping["power"]]
            )
        )

    def forward(
        self,
        mass_flow_rate: torch.Tensor
    ):
        if self.learnable:
            return self.power_curve(mass_flow_rate)
        else:
            design_power = self.config.power.design_power_consumption
            design_flow_rate = self.config.cooling.design_maximum_flow_rate
            if design_power == "autosize" or design_flow_rate == "autosize":
                try:
                    data, _ = self.buffer.sample(10)
                    power = data.pump_power.mean()
                    return torch.tensor(power, dtype=torch.float32).view(-1, 1)
                except:
                    return torch.zeros_like(mass_flow_rate).view(-1, 1)
            vol_flow_rate = mass_flow_rate / rho_water
            flow_fraction = torch.clip(vol_flow_rate / design_flow_rate, 0, 1)
            coef1 = self.config.power.coefficient_1_of_the_part_load_performance_curve
            coef2 = self.config.power.coefficient_2_of_the_part_load_performance_curve
            coef3 = self.config.power.coefficient_3_of_the_part_load_performance_curve
            coef4 = self.config.power.coefficient_4_of_the_part_load_performance_curve
            power = design_power * (
                coef1 + coef2 * flow_fraction + coef3 * flow_fraction**2 + coef4 * flow_fraction**3
            )
            return power

    def learn(self):
        if self.learnable:
            batch, _ = self.buffer.sample(batch_size=0)
            self.power_curve.learn(
                x=torch.tensor(batch.pump_mass_flow_rate, dtype=torch.float32),
                y=torch.tensor(batch.pump_power, dtype=torch.float32)
            )
        else:
            pass

