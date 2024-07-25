import torch
import torch.nn as nn

from dclib.cooling.plant.facilities import Chiller

from dctwin.models.curves import QuadraticCurve, BiQuadraticCurve
from dctwin.data import Batch, Buffer

from loguru import logger


class ChillerModel(nn.Module):
    """
    Implement the learnable chiller model. The model can take part load ratio as input and output the electric input.
    The power model is a quadratic function of the part load ratio which the parameters are learnable.
    """
    def __init__(
        self, config: Chiller, key_mapping: dict, learnable: bool = True
    ):
        super(ChillerModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        # define model parameters
        self.reference_capacity = config.cooling.reference_capacity
        self.reference_cop = config.cooling.reference_cop
        self.design_power = self.reference_capacity / self.reference_cop
        self.plr_curve = QuadraticCurve(
            init_params=torch.tensor(
                config.power.electric_input_to_cooling_output_ratio_function_of_part_load_ratio_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )
        self.eir_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )
        # define the replay buffer
        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping

    def forward(
        self,
        chw_sp: torch.Tensor,
        cw_sp: torch.Tensor,
        cooling_load: torch.Tensor
    ):
        partial_load = cooling_load / self.config.cooling.reference_capacity
        return self.design_power * self.plr_curve(partial_load) * self.eir_curve(chw_sp, cw_sp)

    def collect(self, data: dict):
        assert "cooling load" in self.key_mapping.keys(), "The \"cooling load\" key is not provided."
        assert "chilled water supply temperature" in self.key_mapping.keys(),\
            "The \"chilled water supply temperature\" key is not provided."
        assert "condenser water supply temperature" in self.key_mapping.keys(),\
            "The \"condensing water supply temperature\" key is not provided."
        assert "power" in self.key_mapping.keys(), "The \"power\" key is not provided."
        assert self.key_mapping["cooling load"] in data.keys(),\
            f"{self.key_mapping['cooling load']} is not included in the data dictionary."
        assert self.key_mapping["chilled water supply temperature"] in data.keys(),\
            f"{self.key_mapping['chilled water supply temperature']} is not included in the data dictionary."
        assert self.key_mapping["condenser water supply temperature"] in data.keys(),\
            f"{self.key_mapping['condenser water supply temperature']} is not included in the data dictionary."
        assert self.key_mapping["power"] in data.keys(),\
            f"{self.key_mapping['power']} is not included in the data dictionary."
        self.buffer.add(
            Batch(
                chiller_cooling_load=data[self.key_mapping["cooling load"]],
                chilled_water_supply_temperature=data[self.key_mapping["chilled water supply temperature"]],
                condensing_water_supply_temperature=data[self.key_mapping["condenser water supply temperature"]],
                chiller_power=data[self.key_mapping["power"]],
            )
        )

    def learn(self):
        if self.learnable:
            batch, _ = self.buffer.sample(batch_size=0)
            mask = batch.chiller_cooling_load > 0
            batch = batch[mask]
            if len(batch) > 3:
                partial_load = batch.chiller_cooling_load / self.config.cooling.reference_capacity
                power_fraction = batch.chiller_power / self.design_power
                self.plr_curve.learn(
                    x=torch.tensor(
                        partial_load, dtype=torch.float32
                    ),
                    y=torch.tensor(
                        power_fraction, dtype=torch.float32
                    ),
                )
            else:
                logger.warning(
                    "No sufficient data is available for learning the chiller model. Skip the learning process."
                )
        else:
            pass
