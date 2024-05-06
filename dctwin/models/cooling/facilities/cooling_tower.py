import torch
import torch.nn as nn

from dclib.cooling.plant.facilities import CoolingTower

from dctwin.data import Batch, Buffer


class CoolingTowerModel(nn.Module):
    """
    Constant speed cooling tower model that always operates at the maximum capacity.
    """
    def __init__(
        self, config: CoolingTower, key_mapping: dict, learnable: bool = True
    ):
        super(CoolingTowerModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping

    def forward(
        self,
        cw_return_water_temperature: torch.Tensor = None,
        cw_return_water_mass_flow_rate: torch.Tensor = None,
        cw_supply_water_temperature: torch.Tensor = None,
        outside_air_wetbulb_temperature: torch.Tensor = None,
    ):
        # By default, the cooling tower is operated at the maximum capacity. Therefore, we use the average power
        # consumption data collected in the online process as the output.
        if not self.learnable:
            if self.config.power.design_fan_power == "autosize":
                try:
                    data, _ = self.buffer.sample(10)
                    power = data.cooling_tower_power.mean()
                    return torch.tensor(power, dtype=torch.float32).mean().view(-1, 1)
                except:
                    return torch.zeros(1)
            
            return torch.tensor(float(self.config.power.design_fan_power), dtype=torch.float32).mean().view(-1, 1)
        else:
            raise NotImplementedError("Learnable cooling tower model is not implemented yet !")

    def collect(self, data: dict):
        self.buffer.add(
            Batch(
                cooling_tower_return_water_temperature=data[self.key_mapping["return water temperature"]],
                cooling_tower_water_mass_flow_rate=data[self.key_mapping["water mass flow rate"]],
                cooling_tower_supply_water_temperature=data[self.key_mapping["supply water temperature"]],
                outside_air_wetbulb_temperature=data[self.key_mapping["outside air wetbulb temperature"]],
                cooling_tower_air_flow_rate_ratio=data[self.key_mapping["cooling tower air flow rate ratio"]],
                cooling_tower_fan_power=data[self.key_mapping["power"]],
            )
        )

    def learn(self):
        if self.learnable:
            raise NotImplementedError("Learnable cooling tower model is not implemented yet !")
        else:
            pass
