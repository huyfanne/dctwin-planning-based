import numpy as np
import torch
import torch.nn as nn

from dclib.cooling.common import Pump

from dctwin.models.utlis import CubicCurve

from dctwin.data import Batch, Buffer
from dctwin.utils.const import rho_water


class PumpModel(nn.Module):
    """
    Implement the learnable pump model. The model can take the mass flow rate as input and output the electric input.
    The power model is a quartic function of the mass flow rate which the parameters are learnable.
    """
    def __init__(
        self,
        config: Pump,
        key_mapping: dict,
        learnable: bool = True,
        device: str | int | torch.device = "cpu",
    ) -> None:
        super(PumpModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        # define the model parameters
        self.design_power = self.config.power.design_power_consumption
        self.design_flow_rate = self.config.cooling.design_maximum_flow_rate
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
        self.device = device

    def collect(self, data: dict):
        self.buffer.add(
            Batch(
                pump_mass_flow_rate=data[self.key_mapping["mass flow rate"]],
                pump_power=data[self.key_mapping["power"]]
            )
        )

    def forward(
        self,
        mass_flow_rate: np.ndarray | torch.Tensor,
    ) -> torch.Tensor:
        mass_flow_rate = torch.as_tensor(mass_flow_rate, device=self.device, dtype=torch.float32)
        flow_fraction = mass_flow_rate / (self.design_flow_rate * rho_water)
        flow_fraction = torch.clip(
            flow_fraction, 0, 1
        )
        return self.design_power * self.power_curve(flow_fraction)

    def learn(self):
        if self.learnable:
            batch, _ = self.buffer.sample(batch_size=0)
            mask = batch.pump_mass_flow_rate > 0
            batch = batch[mask]
            if len(batch) > 3:
                flow_fraction = np.clip(
                    batch.pump_mass_flow_rate / (self.design_flow_rate * rho_water), 0, 1
                )
                power_fraction = batch.pump_power / self.design_power
                self.power_curve.learn(
                    x=torch.tensor(flow_fraction, dtype=torch.float32),
                    y=torch.tensor(power_fraction, dtype=torch.float32)
                )
            else:
                from loguru import logger
                logger.warning(f"Insufficient data for learning the pump model of {self.uid}.")
