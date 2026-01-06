from typing import Dict, Any
from loguru import logger
import torch.nn as nn

import torch
from dclib.room import Room
from CoolProp.CoolProp import HAPropsSI, PropsSI
from dctwin.utils.const import ambient_pressure

from dctwin.models.cooling.facilities import FanModel, DehumidifierModel
from dctwin.models.cooling.thermodyns import SteadyStateThermodynamics
from dctwin.data import Batch


class AirLoopManager(nn.Module):
    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Dict,
        time_step: float = None,
    ) -> None:
        super().__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.time_step = time_step
        self.models = self._init_models()

        self.zone_air_leakage_rate = nn.Parameter(
            torch.tensor(0.0, dtype=torch.float32),
            requires_grad=True,
        )  # kg/s

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the zone equipments
        """
        # get the model for each zone equipment of the building
        for zone_name, zone in self.zones.items():
            self.add_module(f"{zone_name} thermodynamics", SteadyStateThermodynamics())
            # get the ACU equipments of the zone
            for acu_name, acu in zone.constructions.acus.items():
                self.add_module(
                    f"{acu_name} fan",
                    FanModel(
                        config=acu,
                        key_mapping=self.device_key_mapping["acus"][acu_name]["fan"],
                    ),
                )
            for (
                dehumidifier_name,
                dehumidifier,
            ) in zone.constructions.dehumidifiers.items():
                self.add_module(
                    f"{dehumidifier_name}",
                    DehumidifierModel(
                        config=dehumidifier,
                        key_mapping=self.device_key_mapping["dehumidifiers"][
                            dehumidifier_name
                        ],
                    ),
                )
        return {
            k: v
            for k, v in dict(self.named_modules()).items()
            if k != "" and "." not in k
        }

    def collect(self, data: Batch | Dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        for model_name, model in self.models.items():
            if model_name.endswith("fan"):
                model.collect(data)

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for model_name, model in self.models.items():
            if model_name.endswith("fan"):
                model.learn()

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
        humidity: float | torch.Tensor,
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
                humidity,
                "T",
                temperature_k,
                "P",
                ambient_pressure,
            )
            return prop
        except ValueError as e:
            logger.error(f"Error: {e:.2f}")

    def _sim_acu(
        self,
        zone_name: str,
        zone: Room,
        data: Batch,
    ) -> None:
        # get the current zone air humidity ratio
        zone_air_humidity_ratio = data.obs.zones[zone_name].zone_air_humidity_ratio
        zone_air_relative_humidity = self.get_humid_air_property(
            humidity=zone_air_humidity_ratio.item(),
            temperature=data.obs.zones[zone_name].zone_air_temperature.item(),
            property_type="relative_humidity",
        )
        zone_air_relative_humidity = torch.tensor(zone_air_relative_humidity)
        data.obs.zones[
            zone_name
        ].zone_air_relative_humidity = zone_air_relative_humidity
        # get the active acu ids
        active_acu_ids = [
            acu_name
            for acu_name, acu in zone.constructions.acus.items()
            if data.acts[acu_name].on_off_schedule == 1
        ]
        # uniform distribution of the heat load among active ACUs
        zone_acu_heat_load = {
            active_acu_name: data.obs_next.zones[zone_name].sensible_heat_load
            / len(active_acu_ids)
            for active_acu_name in active_acu_ids
        }
        weighted_return_temperature = torch.zeros(
            1,
        )
        total_acu_air_mass_flow_rate = torch.zeros(
            1,
        )
        for acu_name, acu in zone.constructions.acus.items():
            data.obs_next.zones[acu_name].supply_air_temperature = data.acts[
                acu_name
            ].supply_temperature_sp
            supply_air_relative_humidity = self.get_humid_air_property(
                humidity=zone_air_humidity_ratio.item(),
                temperature=data.obs_next.zones[acu_name].supply_air_temperature.item(),
                property_type="relative_humidity",
            )
            data.obs_next.zones[acu_name].supply_air_relative_humidity = torch.tensor(
                supply_air_relative_humidity
            )
            if acu_name in active_acu_ids:
                data.obs_next.zones[acu_name].supply_air_mass_flow_rate = data.acts[
                    acu_name
                ].supply_mass_flow_rate_sp
                # calculate the fan power and the return air temperature
                data.obs_next.zones[acu_name].fan_power = self.models[
                    f"{acu_name} fan"
                ](data.acts[acu_name].supply_mass_flow_rate_sp)
                acu_return_temperature = self.models[
                    f"{zone_name} thermodynamics"
                ].forward(
                    supply_air_temperature=data.acts[acu_name].supply_temperature_sp,
                    supply_air_mass_flow_rate=data.acts[
                        acu_name
                    ].supply_mass_flow_rate_sp,
                    sensible_heat_load=zone_acu_heat_load[acu_name],
                )
                data.obs_next.zones[
                    acu_name
                ].return_air_temperature = acu_return_temperature
                weighted_return_temperature += (
                    acu_return_temperature
                    * data.acts[acu_name].supply_mass_flow_rate_sp
                )
                total_acu_air_mass_flow_rate += data.acts[
                    acu_name
                ].supply_mass_flow_rate_sp
            else:
                data.obs_next.zones[acu_name].supply_air_mass_flow_rate = torch.zeros(
                    1,
                )
                data.obs_next.zones[acu_name].fan_power = torch.zeros(
                    1,
                )
                data.obs_next.zones[
                    acu_name
                ].return_air_temperature = data.obs_next.zones[
                    acu_name
                ].supply_air_temperature
            return_air_relative_humidity = self.get_humid_air_property(
                humidity=zone_air_humidity_ratio.item(),
                temperature=data.obs_next.zones[acu_name].return_air_temperature.item(),
                property_type="relative_humidity",
            )
            data.obs_next.zones[acu_name].return_air_relative_humidity = torch.tensor(
                return_air_relative_humidity
            )

        # update the next zone air temperature and humidity ratio
        data.obs_next.zones[zone_name].zone_air_temperature = (
            weighted_return_temperature / total_acu_air_mass_flow_rate
        )
        zone_air_relative_humidity = self.get_humid_air_property(
            humidity=zone_air_humidity_ratio.item(),
            temperature=data.obs_next.zones[zone_name].zone_air_temperature.item(),
            property_type="relative_humidity",
        )
        zone_air_relative_humidity = torch.tensor(zone_air_relative_humidity)
        data.obs_next.zones[
            zone_name
        ].zone_air_relative_humidity = zone_air_relative_humidity
        data.obs_next.zones[zone_name].zone_air_humidity_ratio = zone_air_humidity_ratio

    def _sim_dehumidifier(
        self,
        zone_name: str,
        zone: Room,
        data: Batch,
    ) -> None:
        rho_air = self.get_fluid_property(
            fluid_name="air",
            temperature=data.obs.zones[zone_name].zone_air_temperature.item(),
            property_type="density",
        )
        zone_air_humidity_ratio = data.obs.zones[zone_name].zone_air_humidity_ratio
        zone_moisture = (
            zone_air_humidity_ratio * rho_air * zone.geometry.volume
        )  # kg water
        # update the zone moisture based on the outdoor air humidity ratio and leakage rate
        zone_moisture += (
            (data.inps.outdoor_air_humidity_ratio - zone_air_humidity_ratio)
            * zone.geometry.volume
            * rho_air
            * self.zone_air_leakage_rate
            * self.time_step
        )
        data.obs.zones[zone_name].zone_moisture = zone_moisture
        # get the active dehumidifier ids
        active_dehumidifier_ids = [
            dehumidifier_name
            for dehumidifier_name, dehumidifier in zone.constructions.dehumidifiers.items()
            if data.acts[dehumidifier_name].on_off_schedule == 1
        ]
        for dehumidifier_name, dehumidifier in zone.constructions.dehumidifiers.items():
            data.obs.zones[dehumidifier_name].inlet_air_temperature = data.obs.zones[
                zone_name
            ].zone_air_temperature
            data.obs.zones[
                dehumidifier_name
            ].inlet_air_relative_humidity = data.obs.zones[
                zone_name
            ].zone_air_relative_humidity
            if dehumidifier_name in active_dehumidifier_ids:
                # dehumidifier is on
                (
                    power,
                    outlet_temp,
                    outlet_rh,
                    water_removal_rate,
                    supply_air_mass_flow_rate,
                ) = self.models[f"{dehumidifier_name}"](
                    inlet_dry_bulb_temperature=data.obs.zones[
                        dehumidifier_name
                    ].inlet_air_temperature,
                    inlet_relative_humidity=data.obs.zones[
                        dehumidifier_name
                    ].inlet_air_relative_humidity,
                    relative_humidity_setpoint=data.acts[
                        dehumidifier_name
                    ].relative_humidity_sp,
                )
                # calculate room humidity ratio and relative humidity
                zone_moisture = zone_moisture - water_removal_rate * self.time_step
                zone_air_humidity_ratio = zone_moisture / (
                    zone.geometry.volume * rho_air
                )
            else:
                # dehumidifier is off
                power, water_removal_rate, supply_air_mass_flow_rate = (
                    torch.zeros(
                        1,
                    ),
                    torch.zeros(
                        1,
                    ),
                    torch.zeros(
                        1,
                    ),
                )
                outlet_temp = data.obs.zones[dehumidifier_name].inlet_air_temperature
                outlet_rh = data.obs.zones[
                    dehumidifier_name
                ].inlet_air_relative_humidity
                zone_air_humidity_ratio = zone_moisture / (
                    zone.geometry.volume * rho_air
                )
            # update the next dehumidifier states
            data.obs_next.zones[dehumidifier_name].power = power
            data.obs_next.zones[dehumidifier_name].outlet_air_temperature = outlet_temp
            data.obs_next.zones[
                dehumidifier_name
            ].outlet_air_relative_humidity = outlet_rh
            data.obs_next.zones[
                dehumidifier_name
            ].water_removal_rate = water_removal_rate
            data.obs_next.zones[
                dehumidifier_name
            ].supply_air_mass_flow_rate = supply_air_mass_flow_rate
            data.obs_next.zones[
                dehumidifier_name
            ].inlet_air_temperature = data.obs_next.zones[
                zone_name
            ].zone_air_temperature
            data.obs_next.zones[
                dehumidifier_name
            ].inlet_air_relative_humidity = data.obs_next.zones[
                zone_name
            ].zone_air_relative_humidity
            data.obs_next.zones[dehumidifier_name].outlet_air_temperature = outlet_temp
            data.obs_next.zones[
                dehumidifier_name
            ].outlet_air_relative_humidity = outlet_rh

        # update the next zone air temperature and humidity ratio
        zone_air_relative_humidity = self.get_humid_air_property(
            humidity=zone_air_humidity_ratio.item(),
            temperature=data.obs_next.zones[zone_name].zone_air_temperature.item(),
            property_type="relative_humidity",
        )
        zone_air_relative_humidity = torch.tensor(zone_air_relative_humidity)
        data.obs_next.zones[zone_name].zone_air_humidity_ratio = zone_air_humidity_ratio
        data.obs_next.zones[
            zone_name
        ].zone_air_relative_humidity = zone_air_relative_humidity
        data.obs_next.zones[zone_name].zone_moisture = zone_moisture

    def forward(self, data: Batch) -> None:
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        for zone_name, zone in self.zones.items():
            # simulate the zone equipment
            self._sim_acu(zone_name, zone, data)
            self._sim_dehumidifier(zone_name, zone, data)

            # TODO: calculate the zone ITE inlet temperature
