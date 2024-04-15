import torch
import torch.nn as nn

from dclib.cooling.room.facilities.acu import ACU

from dctwin.models.curves import CubicCurve

from dctwin.data import Batch, Buffer


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
        self.buffer = Buffer(size=100)
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
        return self.power_curve(mass_flow_rate)

    def learn(self):
        if self.learnable:
            batch, _ = self.buffer.sample(batch_size=0)
            self.power_curve.learn(
                torch.tensor(batch.supply_air_mass_flow_rate, dtype=torch.float32),
                torch.tensor(batch.fan_power)
            )
        else:
            pass
