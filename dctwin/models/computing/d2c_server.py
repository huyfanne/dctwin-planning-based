from typing import Tuple
import torch
import torch.nn as nn

from dclib.ite.servers.server import Server
from dctwin.data import Buffer
from dctwin.utils.const import water_specific_heat


class ChipThermoModel(nn.Module):
    def __init__(
        self,
        learnable: bool = True,
        a: float = 1.04,
        b: float = 1.44 * 0.0016
    ) -> None:
        super(ChipThermoModel, self).__init__()
        self.a = nn.Parameter(torch.tensor(a))
        self.b = nn.Parameter(torch.tensor(b))
        self.learnable = learnable

    def forward(
        self,
        T_in: torch.Tensor,
        power: torch.Tensor,
        mass_flow_rate: torch.Tensor
    ) -> torch.Tensor:
        """
        Simulate the maximum temperature of the server chip based on the empirical formula.
        """
        return self.a * T_in + self.b * power / (mass_flow_rate * water_specific_heat)

class HybridCoolingLoadDistributionModel(nn.Module):
    def __init__(
        self,
        learnable: bool = True,
        a: float = 0.009633,
        b: float = -0.07046,
        c: float =-0.002658,
        d: float = 0.07515,
        e: float = -0.001991,
        f: float =-0.0003291
    ) -> None:
        """
        Simulate the dynamic cooling load distribution of the air-side and water-side. The model is based on the
        empirical formula obtained from server level CFD simulation
        """
        super(HybridCoolingLoadDistributionModel, self).__init__()
        self.a = nn.Parameter(torch.tensor(a))
        self.b = nn.Parameter(torch.tensor(b))
        self.c = nn.Parameter(torch.tensor(c))
        self.d = nn.Parameter(torch.tensor(d))
        self.e = nn.Parameter(torch.tensor(e))
        self.f = nn.Parameter(torch.tensor(f))
        self.learnable = learnable

    def forward(
        self,
        T_water_in: torch.Tensor,
        m_water_in: torch.Tensor,
        T_air_in: torch.Tensor,
        m_air_in: torch.Tensor,
        power: torch.Tensor
    ) -> torch.Tensor:
        """
        ((𝑎+𝑏𝑚_𝑎^(−0.6)−𝑐𝑚_𝑎^(−1) )𝑄+𝑇_(𝑤,𝑖)−𝑇_(𝑎,𝑖))/(𝑏𝑚_𝑎^(−0.6)−𝑐𝑚_𝑎^(−1)+𝑑+𝑒𝑚_𝑤^(−0.8)−𝑓𝑚_𝑤^(−1) )𝑄
        """
        eta_nominator = (self.a + self.b * m_air_in**(-0.6) - self.c * m_air_in**(-1)) * power + T_water_in - T_air_in
        eta_denominator = (
            self.b * m_air_in**(-0.6) - self.c * m_water_in**(-1) + self.d +
            self.e * m_water_in**(-0.8) - self.f * m_water_in**(-1)
        ) * power
        return eta_nominator / (eta_denominator+1e-9)

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
        self.models = self._init_models()

    @staticmethod
    def _init_models():
        chip_thermo_model = ChipThermoModel()
        cooling_load_distribution_model = HybridCoolingLoadDistributionModel()
        return {
            "chip_max_temperature_model": chip_thermo_model,
            "cooling_load_distribution_model": cooling_load_distribution_model
        }

    def forward(
        self,
        server_power: torch.Tensor,
        inlet_liquid_temperature: torch.Tensor,
        inlet_liquid_mass_flow_rate: torch.Tensor,
        inlet_air_temperature: torch.Tensor = 25.,
        inlet_air_mass_flow_rate: torch.Tensor = 0.5,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Simulate the server friction power due to the liquid cooling pipes installed in the chips.
        """
        eta = self.models["cooling_load_distribution_model"].forward(
            T_water_in=inlet_liquid_temperature,
            m_water_in=inlet_liquid_mass_flow_rate,
            T_air_in=inlet_air_temperature,
            m_air_in=inlet_air_mass_flow_rate,
            power=server_power
        )
        liquid_cooled_power = server_power * eta
        # server total power
        liquid_outlet_temperature = inlet_liquid_temperature + liquid_cooled_power / (
            water_specific_heat * inlet_liquid_mass_flow_rate
        )
        # empirical formula for the maximum temperature of the CPU based on chip-level CFD simulation
        cpu_max_temperature = self.models["chip_max_temperature_model"].forward(
            T_in=inlet_liquid_temperature,
            power=liquid_cooled_power,
            mass_flow_rate=inlet_liquid_mass_flow_rate
        )
        return liquid_outlet_temperature, cpu_max_temperature, liquid_cooled_power

    def collect(self, data: dict):
        pass

    def learn(self):
        pass


if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import numpy as np

    T_water = np.linspace(25, 40, 100)
    m_water = 0.05
    T_air = 25
    m_air = 0.5
    power = 1000

    eta_nominator = (
        (0.009633 + -0.07046 * m_air**(-0.6) - -0.002658 * m_air**(-1)) * power + T_water - T_air
    )
    eta_denominator = (
        -0.07046 * m_air**(-0.6) - -0.002658 * m_water**(-1) + 0.07515 +
        -0.001991 * m_water**(-0.8) - -0.0003291 * m_water**(-1)
    ) * power
    eta = eta_nominator / (eta_denominator+1e-9)

    plt.plot(T_water, eta)
    plt.xlabel("Water temperature")
    plt.ylabel("Eta")
    plt.show()


