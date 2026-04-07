from typing import Tuple
import torch
import torch.nn as nn

from dclib.ite.servers.server import Server
from dctwin.data import Buffer
from dctwin.utils.const import water_specific_heat, air_specific_heat


class ChipThermoModel(nn.Module):
    def __init__(
        self,
        chip_heat_transfer_area: float | torch.Tensor = 0.26
        * 0.11,  # heat transfer area of the chip
        chip_thickness: float | torch.Tensor = 0.03,  # for typical Intel CPU chip
        conductivity_silicon: float | torch.Tensor = 148.0,  # for copper
        alpha: float | torch.Tensor = 1.0,
        learnable: bool = True,
    ) -> None:
        super(ChipThermoModel, self).__init__()
        self.alpha = nn.Parameter(torch.tensor(alpha), requires_grad=learnable)
        self.chip_thickness = nn.Parameter(
            torch.tensor(chip_thickness), requires_grad=learnable
        )
        self.chip_heat_transfer_area = nn.Parameter(
            torch.tensor(chip_heat_transfer_area), requires_grad=learnable
        )
        self.conductivity_silicon = conductivity_silicon

    def forward(
        self,
        T_in: torch.Tensor,
        power: torch.Tensor,
        liquid_mass_flow_rate: torch.Tensor,
        h_water: torch.Tensor,
    ) -> torch.Tensor:
        """
        Simulate the maximum temperature of the server chip based on the empirical formula:

                        T_chip,max = Tw,in + alpha * P / S * (1/h_w + L / k_s + S / (m_w * Cp,w))

        where:
        Tw,in: the inlet temperature of the liquid cooling system
        alpha: the empirical coefficient for correcting the maximum temperature
        P: the power consumption of the server
        S: the heat transfer area of the chip
        h_w: the convective heat transfer coefficient of the liquid cooling system
        L: the thickness of the chip
        k_s: the thermal conductivity of the silicon
        m_w: the mass flow rate of the liquid cooling system
        Cp,w: the specific heat capacity of the liquid cooling system

        The model is validated with the experimental data from the following article:
        TODO: check the model output with the experimental data
        """
        assert liquid_mass_flow_rate.item() > 1e-6, ValueError(
            f"Invalid liquid mass flow rate: {liquid_mass_flow_rate.item()}"
        )
        T_max = T_in + self.alpha * power / self.chip_heat_transfer_area * (
            1 / h_water
            + self.chip_thickness / self.conductivity_silicon
            + self.chip_heat_transfer_area
            / (liquid_mass_flow_rate * water_specific_heat)
        )
        return T_max


class HybridCoolingLoadDistributionModel(nn.Module):
    def __init__(
        self,
        num_turn: int = 4,
        air_heat_transfer_multiplication_factor: float | torch.Tensor = 5.0,
        pipe_diameter: float
        | torch.Tensor = 0.05,  # pipe diameter of the liquid cooling system
        chip_characteristic_length: float | torch.Tensor = 0.04,  # length of the chip
        cold_plate_thickness: float | torch.Tensor = 0.01,
        conductivity_solid: float | torch.Tensor = 400.0,  # for copper
        air_ventilation_area: float | torch.Tensor = 0.04 * 1.0,
        learnable: bool = True,
    ) -> None:
        """
        Simulate the dynamic cooling load distribution of the air-side and water-side. The model is based on the
        thermal resistance network analysis of the hybrid cooling system. The thermal resistance is derived from the
        conductive and convective heat transfer principles considering the server and cold plate geometry. The results
        are comparable with the experimental data from the following article:

        [1] Shalom Simon, et al. CFD analysis of Heat capture ratio in a hybrid cooled server. In International Electronic Packaging Technical Conference and Exhibition (Vol. 86557, p. V001T01A013). American Society of Mechanical Engineers.
        """
        super(HybridCoolingLoadDistributionModel, self).__init__()
        self.num_turn = num_turn
        self.air_heat_transfer_multiplication_factor = nn.Parameter(
            torch.tensor(air_heat_transfer_multiplication_factor),
            requires_grad=learnable,
        )
        self.pipe_diameter = nn.Parameter(
            torch.tensor(pipe_diameter), requires_grad=learnable
        )
        self.chip_characteristic_length = nn.Parameter(
            torch.tensor(chip_characteristic_length)
        )
        self.cold_plate_thickness = nn.Parameter(torch.tensor(cold_plate_thickness))
        self.air_ventilation_area = air_ventilation_area

        # constant numbers
        self.conductivity_solid = conductivity_solid
        self.viscosity_air = 185 * 10 ** (-7)
        self.prandtl_air = 0.7
        self.conductivity_air = 26 * 10 ** (-3)
        self.viscosity_water = 900 * 10 ** (-6)
        self.prandtl_water = 6.62
        self.conductivity_water = 0.6

    def forward(
        self,
        T_water_in: torch.Tensor,
        m_water_in: torch.Tensor,
        T_air_in: torch.Tensor,
        m_air_in: torch.Tensor,
        power: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        reynolds_air = (
            m_air_in / self.air_ventilation_area * self.chip_characteristic_length
        ) / self.viscosity_air
        nu_air = 0.664 * reynolds_air**0.6 * self.prandtl_air ** (1 / 3)  # 0
        reynolds_water = (
            m_water_in / (torch.pi * self.pipe_diameter**2 / 4) * self.pipe_diameter
        ) / self.viscosity_water
        nu_water = 0.023 * reynolds_water**0.8 * self.prandtl_water ** (1 / 3)

        h_air = nu_air * self.conductivity_air / self.chip_characteristic_length
        h_water = nu_water * self.conductivity_water / self.pipe_diameter
        heat_transfer_area_water = (
            torch.pi
            * self.pipe_diameter
            * self.chip_characteristic_length
            * self.num_turn
        )
        heat_transfer_area_air = (
            self.chip_characteristic_length**2
            * self.air_heat_transfer_multiplication_factor
        )

        M = self.cold_plate_thickness * 0.5 / (
            self.conductivity_solid * heat_transfer_area_water
        ) + 1.0 / (h_water * heat_transfer_area_water)
        N = self.cold_plate_thickness / (
            self.conductivity_solid * heat_transfer_area_air
        ) + 1.0 / (h_air * heat_transfer_area_air)

        eta_nominator = (
            (-T_water_in + T_air_in)
            + power * N
            + power / (m_water_in * air_specific_heat)
        )
        eta_denominator = power * (
            M
            + N
            + 1.0 / (m_water_in * water_specific_heat)
            + 1.0 / (m_air_in * air_specific_heat)
        )
        eta = eta_nominator / (eta_denominator + 1e-9)
        assert 0.0 <= eta.item() <= 1.0, ValueError(
            f"Invalid eta value {eta.item()} found, eta should be in [0, 1] !"
        )
        return eta, h_air, h_water


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
        device: str | torch.device = "cpu",
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
            "cooling_load_distribution_model": cooling_load_distribution_model,
        }

    def forward(
        self,
        server_power: torch.Tensor,
        inlet_liquid_temperature: torch.Tensor,
        inlet_liquid_mass_flow_rate: torch.Tensor,
        inlet_air_temperature: torch.Tensor = 25.0,
        inlet_air_mass_flow_rate: torch.Tensor = 0.05,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Simulate the server friction power due to the liquid cooling pipes installed in the chips.
        """
        eta, h_air, h_water = self.models["cooling_load_distribution_model"].forward(
            T_water_in=inlet_liquid_temperature,
            m_water_in=inlet_liquid_mass_flow_rate,
            T_air_in=inlet_air_temperature,
            m_air_in=inlet_air_mass_flow_rate,
            power=server_power,
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
            liquid_mass_flow_rate=inlet_liquid_mass_flow_rate,
            h_water=h_water,
        )
        return liquid_outlet_temperature, cpu_max_temperature, liquid_cooled_power

    def collect(self, data: dict):
        pass

    def learn(self):
        pass
