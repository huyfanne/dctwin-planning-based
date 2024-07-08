import torch
import torch.nn as nn
from loguru import logger

from dclib.cooling.room.facilities.acu import ACU

from dctwin.models.curves import CubicCurve
from dctwin.data import Batch, Buffer

from dctwin.utils.const import rho_air


class FanModel(nn.Module):
    """
    Implement the learnable Variable Volume Fan model. The model can take the air mass flow rate as input and output the
    electric consumption. The power model is a cubic function of the air mass flow rate which the parameters are
    learnable.
    """
    def __init__(
        self,
        config: ACU,
        key_mapping: dict,
        learnable: bool = True
    ):
        super(FanModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        # define the model parameters
        self.design_volume_flow_rate = config.cooling.design_air_flow_rate
        if config.cooling.design_air_flow_rate != "" and config.cooling.pressure_rise != "":
            self.design_power = (
                self.design_volume_flow_rate * config.cooling.pressure_rise / config.power.fan_total_efficiency
            )
        else:
            logger.warning(
                f"The design volume flow rate or the design pressure rise is not provided for the fan {self.uid}."
            )
            self.design_power = 7500  # default fan power consumption is around 7.5 kW
        self.power_curve = CubicCurve(
            init_params=torch.tensor(
                [
                    config.power.fan_power_coefficient_1,
                    config.power.fan_power_coefficient_2,
                    config.power.fan_power_coefficient_3,
                    config.power.fan_power_coefficient_4,
                ],
                dtype=torch.float32
            ),
            requires_grad=learnable
        )
        # initialize the replay buffer
        self.buffer = Buffer(size=1000)
        self.key_mapping = key_mapping

    def collect(self, data: dict):
        assert "air mass flow rate" in self.key_mapping.keys(), "The \"air mass flow rate\" key is not provided."
        assert "power" in self.key_mapping.keys(), "The \"power\" key is not provided."
        assert self.key_mapping["air mass flow rate"] in data.keys(),\
            f"{self.key_mapping['air mass flow rate']} is not included in the data dictionary."
        assert self.key_mapping["power"] in data.keys(),\
            f"{self.key_mapping['power']} is not included in the data dictionary."
        self.buffer.add(
            Batch(
                supply_air_mass_flow_rate=data[self.key_mapping["air mass flow rate"]],
                fan_power=data[self.key_mapping["power"]]
            )
        )

    def forward(self, mass_flow_rate: torch.Tensor):
        flow_fraction = mass_flow_rate / (self.design_volume_flow_rate * rho_air)
        assert torch.all(flow_fraction <= 1), "The air mass flow rate must be inside [0, 1]."
        return self.design_power * self.power_curve(flow_fraction)

    def learn(self):
        if self.learnable:
            batch, _ = self.buffer.sample(batch_size=0)
            mask = batch.supply_air_mass_flow_rate > 0
            batch = batch[mask]
            if len(batch) > 3:
                flow_fraction = batch.supply_air_mass_flow_rate / (self.design_volume_flow_rate * rho_air)
                power_fraction = batch.fan_power / self.design_power
                self.power_curve.learn(
                    torch.tensor(flow_fraction, dtype=torch.float32),
                    torch.tensor(power_fraction, dtype=torch.float32)
                )
            else:
                from loguru import logger
                logger.warning(f"Insufficient data for learning the fan model of {self.uid}.")
