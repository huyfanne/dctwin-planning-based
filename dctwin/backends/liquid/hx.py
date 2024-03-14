import math

import numpy as np
from CoolProp.CoolProp import PropsSI
from loguru import logger

from .utils import reynolds_number, nusselt_number, friction_factor


class HeatExchanger:
    """
    Implementation of a liquid-to-liquid heat exchanger model based on NTU-effectiveness numerical heat transfer
    theory. The heat exchanger is a cross-flow heat exchanger with a single pass on both the hot and cold sides.
    A root-fining solver is implemented to determine the chilled water mass flow rate given the outlet temperature
    setpoint. The forward only simulation mode is also supported by simply providing the chilled water mass flow rate.

    Reference: Incropera, Frank P., et al. Fundamentals of heat and mass transfer. Vol. 6. New York: Wiley, 1996.
    """
    def __init__(
        self,
        cdu_uid: str,
        tube_diameter: float,
        tube_length: float,
        tube_wall_thickness: float,
        num_row: int,
        num_transverse: int,
        row_pitch: float,
        transverse_pitch: float,
        tube_roughness: float,
        thermal_conductivity: float,
        tol: float = 1e-3,
        max_iter: int = 100
    ):
        # geometry parameters
        self.cdu_uid = cdu_uid
        self.tube_diameter = tube_diameter
        self.tube_length = tube_length
        self.tube_wall_thickness = tube_wall_thickness
        self.num_row = num_row
        self.num_transverse = num_transverse
        self.row_pitch = row_pitch
        self.transverse_pitch = transverse_pitch
        self.tube_roughness = tube_roughness
        self.thermal_conductivity = thermal_conductivity
        self.H_he = num_transverse * transverse_pitch + 2 * tube_diameter
        # solver parameters
        self.tol = tol
        self.max_iter = max_iter

    def _cal_heat_transfer_efficiency(
        self,
        heat_capacity_flow_rate_inside,
        heat_capacity_flow_rate_outside,
        U_total,
        area_heat_exchanger
    ):
        if heat_capacity_flow_rate_inside < heat_capacity_flow_rate_outside:
            heat_capacity_flow_rate_ratio = heat_capacity_flow_rate_inside / heat_capacity_flow_rate_outside
            heat_capacity_flow_rate_min = heat_capacity_flow_rate_inside
            NTU = U_total * area_heat_exchanger / heat_capacity_flow_rate_min
            CC = np.exp(-heat_capacity_flow_rate_ratio * (1 - np.exp(-NTU)))
            efficiency = (1 - CC) / heat_capacity_flow_rate_ratio  # efficiency of heat exchanger
        else:
            heat_capacity_flow_rate_ratio = heat_capacity_flow_rate_outside / heat_capacity_flow_rate_inside
            heat_capacity_flow_rate_min = heat_capacity_flow_rate_outside
            NTU = U_total * area_heat_exchanger / heat_capacity_flow_rate_min
            CC = 1 - np.exp(-heat_capacity_flow_rate_ratio * NTU)
            efficiency = 1 - np.exp(-CC / heat_capacity_flow_rate_ratio)
        return efficiency, NTU

    def _nusselt_number_inner(self, relative_roughness, Reynolds_number, Prandtl_number):
        fr = friction_factor(relative_roughness, Reynolds_number)
        if Reynolds_number <= 2300:
            Nusselt_number = 4.01
        else:
            Nusselt_number = (
                (fr/8) * (Reynolds_number - 1000) * Prandtl_number / (1+12.7*(fr/8)**0.5 * (Prandtl_number**(2/3) - 1))
            )
        return fr, Nusselt_number

    def forward(
        self,
        inner_inlet_temperature: float | np.ndarray,
        inner_mass_flow_rate: float | np.ndarray,
        outer_inlet_temperature: float | np.ndarray,
        outer_mass_flow_rate: float | np.ndarray,
        inlet_fluid: str = "water",
        outlet_fluid: str = "water",
    ):
        # fluid properties
        inner_pressure = 101325
        rho_i = PropsSI('D', 'P', inner_pressure, 'T', inner_inlet_temperature + 273.15, inlet_fluid)
        Cp_i = PropsSI('C', 'P', inner_pressure, 'T', 300, inlet_fluid)
        k_i = PropsSI('CONDUCTIVITY', 'P', inner_pressure, 'T', inner_inlet_temperature + 273.15, inlet_fluid)
        miu_i = PropsSI('V', 'P', inner_pressure, 'T', inner_inlet_temperature + 273.15, inlet_fluid)
        Pr_i = PropsSI('PRANDTL', 'P', inner_pressure, 'T', inner_inlet_temperature + 273.15, inlet_fluid)

        outer_pressure = 101325
        rho_o = PropsSI('D', 'P', outer_pressure, 'T', outer_inlet_temperature + 273.15, outlet_fluid)
        Cp_o = PropsSI('C', 'P', outer_pressure, 'T', 300, outlet_fluid)
        k_o = PropsSI('CONDUCTIVITY', 'P', outer_pressure, 'T', outer_inlet_temperature + 273.15, outlet_fluid)
        miu_o = PropsSI('V', 'P', outer_pressure, 'T', outer_inlet_temperature + 273.15, outlet_fluid)
        Pr_o = PropsSI('PRANDTL', 'P', outer_pressure, 'T', outer_inlet_temperature + 273.15, outlet_fluid)

        # tube inside
        inner_volumetric_flow_rate = inner_mass_flow_rate / rho_i
        u_i = inner_volumetric_flow_rate / (self.num_row * self.num_transverse) / (math.pi/4 * self.tube_diameter**2)
        inner_reynold_number = reynolds_number(
            u_i,
            self.tube_diameter,
            rho_i,
            miu_i
        )
        inner_relative_roughness = self.tube_roughness / self.tube_diameter
        fr, Nu_i = self._nusselt_number_inner(
            relative_roughness=inner_relative_roughness,
            Reynolds_number=inner_reynold_number,
            Prandtl_number=Pr_i
        )
        h_i = Nu_i * k_i / self.tube_diameter

        inner_pressure_drop = fr * (self.tube_length / self.tube_diameter) * (rho_i * u_i ** 2) / 2
        PumpP_i = (self.num_row * self.num_transverse) * inner_pressure_drop * inner_volumetric_flow_rate

        # tube outside
        u_o = outer_mass_flow_rate / rho_o / (self.tube_length * self.H_he)
        u_omax = self.transverse_pitch / (self.transverse_pitch - self.tube_diameter) * u_o
        Re_omax = rho_o * u_omax * self.tube_diameter / miu_o
        coef1, expo1 = nusselt_number(Re_omax)
        Nu_o = coef1 * (Re_omax ** expo1) * (Pr_o ** 0.36)
        if self.num_row < 20:
            N_list = np.array([1, 2, 3, 4, 5, 7, 10, 13, 16])
            N_list = abs(N_list - np.array(self.num_row))
            coef2_list = [0.7, 0.8, 0.86, 0.9, 0.92, 0.95, 0.97, 0.98, 0.99]
            min_id = np.where(N_list == np.min(N_list))[0]
            coef2 = coef2_list[min_id[0]]
            Nu_o = Nu_o * coef2
        h_o = Nu_o * k_o / self.tube_diameter

        f_o = 0.2
        dP_o = self.num_row * (rho_o * u_omax ** 2 / 2) * f_o
        PumpP_o = dP_o * (outer_mass_flow_rate / rho_o)

        # pumping power, U value and NTU value
        friction_power = PumpP_i + PumpP_o
        U = 1 / (
            1 / h_i +
            1 / h_o +
            np.log((self.tube_wall_thickness + self.tube_diameter) / self.tube_diameter) *
            self.tube_diameter / self.thermal_conductivity
        )
        A_he = self.num_row * self.num_transverse * (np.pi * self.tube_diameter * self.tube_length)

        inner_stream_capacity = inner_mass_flow_rate * Cp_i
        outer_stream_capacity = outer_mass_flow_rate * Cp_o
        min_stream_capacity = min(inner_stream_capacity, outer_stream_capacity)
        eff, NTU = self._cal_heat_transfer_efficiency(
            heat_capacity_flow_rate_inside=inner_stream_capacity,
            heat_capacity_flow_rate_outside=outer_stream_capacity,
            U_total=U,
            area_heat_exchanger=A_he
        )
        Q_max = abs(min_stream_capacity * (outer_inlet_temperature - inner_inlet_temperature))
        heat_transfer_rate = eff * Q_max
        outer_outlet_temperature = outer_inlet_temperature - heat_transfer_rate / outer_stream_capacity
        inner_outlet_temperature = (
            inner_inlet_temperature + (heat_transfer_rate) / inner_stream_capacity
        )
        if friction_power / heat_transfer_rate > 0.1:
            logger.warning(
                f"Pump mechanical power: {friction_power:.3f} is higher than 10% of total heat transfer rate:"
                f" {heat_transfer_rate:.3f}, please check if the flow rate is too"
            )
        info = {
            "NTU": NTU,
            "eff": eff,
            "friction_power": friction_power,
            "heat_transfer_rate": heat_transfer_rate,
        }
        return (
            inner_outlet_temperature,
            outer_outlet_temperature,
            info
        )

    def sim(
        self,
        inner_inlet_temperature: float | np.ndarray,
        outer_inlet_temperature: float | np.ndarray,
        outer_mass_flow_rate: float | np.ndarray,
        inner_mass_flow_rate: float | np.ndarray = None,
    ):
        inner_outlet_temperature, outer_outlet_temperature, info = self.forward(
            inner_inlet_temperature=inner_inlet_temperature,
            inner_mass_flow_rate=inner_mass_flow_rate,
            outer_inlet_temperature=outer_inlet_temperature,
            outer_mass_flow_rate=outer_mass_flow_rate,
        )
        return inner_outlet_temperature, outer_outlet_temperature, inner_mass_flow_rate, info
