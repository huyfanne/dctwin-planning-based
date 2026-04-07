from typing import Tuple

import torch
import torch.nn as nn
from CoolProp.CoolProp import HAPropsSI, PropsSI
from loguru import logger

from dclib.cooling.room.facilities import Dehumidifier

from dctwin.utils.const import ambient_pressure
from dctwin.data import Buffer
from dctwin.models.utils import QuadraticCurve, BiQuadraticCurve


class DehumidifierModel(nn.Module):
    def __init__(
        self,
        config: Dehumidifier,
        key_mapping: dict = None,
        learnable: bool = True,
        device: str | torch.device = "cpu",
    ) -> None:
        super(DehumidifierModel, self).__init__()
        self.config = config
        self.learnable = learnable
        self.key_mapping = key_mapping

        self.water_removal_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.cooling.water_removal_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )
        self.energy_factor_curve = BiQuadraticCurve(
            init_params=torch.tensor(
                config.power.energy_factor_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )
        self.plf_corr_curve = QuadraticCurve(
            init_params=torch.tensor(
                config.power.part_load_fraction_correlation_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )
        # initialize the replay buffer
        self.buffer = Buffer(size=100)
        self.device = device

    @staticmethod
    def get_fluid_property(
        fluid_name: str,
        temperature: float | torch.Tensor,
        property_type: str,
    ) -> float:
        try:
            # Convert temperature to Kelvin
            temperature_k = (
                temperature + 273.15
            )  # Assuming input temperature is in Celsius
            # Define property mapping
            property_map = {
                "density": "D",
                "specific_heat": "C",
                "enthalpy": "H",
            }
            # Check if the property type is valid
            if property_type not in property_map:
                raise ValueError(f"Invalid property type: {property_type}")
            # Get the property
            prop = PropsSI(
                property_map[property_type],
                "T",
                temperature_k,
                "P",
                ambient_pressure,
                fluid_name,
            )
            return prop
        except ValueError as e:
            logger.error(f"Error: {e:.2f}")

    @staticmethod
    def get_humid_air_property(
        relative_humidity: float | torch.Tensor,
        temperature: float | torch.Tensor,
        property_type: str,
    ) -> float:
        try:
            # Convert temperature to Kelvin
            temperature_k = (
                temperature + 273.15
            )  # Assuming input temperature is in Celsius
            # Define property mapping
            property_map = {
                "humidity": "W",
                "relative_humidity": "RH",
            }
            # Check if the property type is valid
            if property_type not in property_map:
                raise ValueError(f"Invalid property type: {property_type}")

            if property_type == "humidity":
                known_property = "relative_humidity"
            elif property_type == "relative_humidity":
                known_property = "humidity"
            else:
                raise ValueError(f"Invalid property type: {property_type}")

            if known_property not in property_map:
                raise ValueError(f"Invalid property type: {known_property}")
            # Get the property
            prop = HAPropsSI(
                property_map[property_type],
                property_map[known_property],
                relative_humidity,
                "T",
                temperature_k,
                "P",
                ambient_pressure,
            )
            return prop
        except ValueError as e:
            logger.error(f"Error: {e:.2f}")

    def collect(self, data: dict):
        pass

    def learn(self):
        pass

    def forward(
        self,
        inlet_dry_bulb_temperature: torch.Tensor,
        inlet_relative_humidity: torch.Tensor,
        relative_humidity_setpoint: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if relative_humidity_setpoint > inlet_relative_humidity:
            #  Room relative humidity is greater than room relative humidity setpoint.
            #  Dehumidifier is closed
            return (
                torch.zeros(
                    1,
                ),
                inlet_dry_bulb_temperature,
                inlet_relative_humidity,
                torch.zeros(
                    1,
                ),
                torch.zeros(
                    1,
                ),
            )

        rho_air = self.get_fluid_property(
            fluid_name="air",
            temperature=inlet_dry_bulb_temperature.item(),
            property_type="density",
        )
        rho_water = self.get_fluid_property(
            fluid_name="water",
            temperature=inlet_dry_bulb_temperature.item(),
            property_type="density",
        )
        cp_air = self.get_fluid_property(
            fluid_name="air",
            temperature=inlet_dry_bulb_temperature.item(),
            property_type="specific_heat",
        )
        inlet_humidity_ratio = self.get_humid_air_property(
            relative_humidity=inlet_relative_humidity.item(),
            temperature=inlet_dry_bulb_temperature.item(),
            property_type="humidity",
        )
        hfg = PropsSI(
            "H", "T", 273.15 + inlet_dry_bulb_temperature.item(), "Q", 1, "water"
        ) - PropsSI(
            "H", "T", 273.15 + inlet_dry_bulb_temperature.item(), "Q", 0, "water"
        )

        setpoint_humidity_ratio = self.get_humid_air_property(
            relative_humidity=relative_humidity_setpoint.item(),
            temperature=inlet_dry_bulb_temperature.item(),
            property_type="humidity",
        )

        water_removal_met = (
            rho_air
            * self.config.cooling.rated_air_flow_rate
            * (inlet_humidity_ratio - setpoint_humidity_ratio)
        )  # kg/s

        water_removal_rate_factor = self.water_removal_curve(
            inlet_dry_bulb_temperature,
            inlet_relative_humidity * 100,
        )
        water_removal_mass_rate = (
            self.config.cooling.rated_water_removal * water_removal_rate_factor
        )
        steady_state_water_removal_rate = (
            rho_water * water_removal_mass_rate / (24 * 3600 * 1000)
        )  # kg/s

        if steady_state_water_removal_rate > 0:
            part_load_ratio = water_removal_met / steady_state_water_removal_rate
            part_load_ratio = torch.clamp(part_load_ratio, 0, 1)
        else:
            part_load_ratio = 0

        energy_factor_adj_factor = self.energy_factor_curve(
            inlet_dry_bulb_temperature,
            inlet_relative_humidity * 100,
        )

        energy_factor = energy_factor_adj_factor * self.config.power.rated_energy_factor

        if self.plf_corr_curve is not None:
            part_load_fraction = self.plf_corr_curve(part_load_ratio)
        else:
            part_load_fraction = 1

        run_time_fraction = part_load_ratio / part_load_fraction

        steady_state_electric_power = (
            water_removal_mass_rate * 1000 / (energy_factor * 24)
        )  # W
        electric_power_avg = steady_state_electric_power * run_time_fraction
        average_water_removal_rate = (
            steady_state_water_removal_rate * part_load_ratio
        )  # kg/s

        latent_output = steady_state_water_removal_rate * part_load_ratio
        outlet_temperature = inlet_dry_bulb_temperature + (
            steady_state_electric_power + steady_state_water_removal_rate * hfg
        ) / (rho_air * self.config.cooling.rated_air_flow_rate * cp_air)

        outlet_humidity_ratio = inlet_humidity_ratio - latent_output / (
            rho_air * self.config.cooling.rated_air_flow_rate
        )
        outlet_relative_humidity = self.get_humid_air_property(
            relative_humidity=outlet_humidity_ratio.item(),
            temperature=outlet_temperature.item(),
            property_type="relative_humidity",
        )
        outlet_relative_humidity = torch.tensor(
            outlet_relative_humidity, device=self.device
        )
        mass_air_flow_rate = torch.tensor(
            rho_air * self.config.cooling.rated_air_flow_rate
        )

        return (
            electric_power_avg,
            outlet_temperature,
            outlet_relative_humidity,
            average_water_removal_rate,
            mass_air_flow_rate,
        )
