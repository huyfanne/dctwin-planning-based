import torch
import torch.nn as nn
from loguru import logger
from CoolProp.CoolProp import PropsSI
import numpy as np
from scipy.interpolate import interp1d

from dclib.cooling.room.facilities import Pipe
from .utils.parameter_calc import reynolds_number


class PipeModel(nn.Module):
    gravity: float = 9.81

    def __init__(
        self,
        pipe: Pipe,
        sub_pipe_diameter: float = None
    ) -> None:
        super().__init__()
        self.pipe_diameter = torch.tensor(pipe.geometry.pipe_diameter)
        self.pipe_length = torch.tensor(pipe.geometry.pipe_length)
        self.channel_type = pipe.geometry.channel_type
        self.turning_radius = torch.tensor(pipe.geometry.turning_radius)  # for elbow
        self.sub_pipe_diameter = torch.tensor(sub_pipe_diameter) if sub_pipe_diameter else None  # for tee
        self.fluid_density = PropsSI('D', 'P', 101325, 'Q', 0, "water")
        self.fluid_viscosity = PropsSI('V', 'P', 101325, 'Q', 0, "water")
        self.fluid_density = torch.tensor(self.fluid_density)
        self.fluid_viscosity = torch.tensor(self.fluid_viscosity)
        self.height_difference = torch.tensor(pipe.geometry.height_difference)
        self.relative_roughness = torch.tensor(pipe.geometry.roughness / pipe.geometry.pipe_diameter)

    # Reference: https://doi.org/10.1026/(ASCE)0733-9429(2008)134:9(1357)
    def friction_factor(self, fluid_velocity: torch.Tensor):
        """
        Calculate the dynamical friction factor of the pipe w.r.t. fluid velocity.
        """
        reynold_number = reynolds_number(
            fluid_velocity=fluid_velocity,
            pipe_diameter=self.pipe_diameter,
            fluid_density=self.fluid_density,
            fluid_viscosity=self.fluid_viscosity
        )
        a = 1 / (1 + (reynold_number/2720)**9)
        b = 1 / (1 + (self.relative_roughness * reynold_number / 160) ** 2)
        c = (reynold_number / 64) ** a
        d = (1.8 * torch.log10(reynold_number / 6.8)) ** (2 * (1 - a) * b)
        e = (2 * torch.log10(3.7 / self.relative_roughness)) ** (2 * (1 - a) * (1 - b))
        fr = 1 / (c * d * e)  # friction factor
        return fr

    # Reference: Code for designing of cooling tower for mechanical ventilation (GB/T 50352)
    def sim(
        self,
        main_pipe_mass_flow_rate: torch.Tensor,
        sub_pipe_mass_flow_rate: torch.Tensor = None,
    ):
        """
        Simulate the pressure drop and mechanical power consumption of the pipe w.r.t. mass flow rate.
        """
        fluid_velocity = main_pipe_mass_flow_rate / self.fluid_density / (torch.pi * self.pipe_diameter ** 2 / 4)
        if self.channel_type == 'straight':
            friction_factor = self.friction_factor(
                fluid_velocity=fluid_velocity
            )
            friction_coefficient = friction_factor * (self.pipe_length / self.pipe_diameter)
        elif self.channel_type == 'elbow':
            # angle is 90 degree
            x = np.array([0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0])
            y = np.array([1.2, 0.8, 0.6, 0.48, 0.36, 0.3, 0.29])
            interpolation_function = interp1d(x, y, kind='linear')  # linear interpolation
            ratio = np.array([self.turning_radius / self.pipe_diameter])  # R/d
            friction_coefficient = float(interpolation_function(ratio)[0])
        elif self.channel_type == 'tee':
            if sub_pipe_mass_flow_rate is None:
                logger.critical("Sub pipe mass flow rate is required for tee pipe.")
            area_ratio = (self.sub_pipe_diameter / self.pipe_diameter) ** 2
            velocity_ratio = sub_pipe_mass_flow_rate / main_pipe_mass_flow_rate
            if 0 <= area_ratio <= 0.35:
                if velocity_ratio <= 0.4:
                    friction_coefficient = 1.1 - 0.7 * velocity_ratio
                else:
                    friction_coefficient = 0.85
            elif area_ratio > 0.35:
                if velocity_ratio <= 0.6:
                    friction_coefficient = 1 - 0.65 * velocity_ratio
                else:
                    friction_coefficient = 0.6
        # calculate pressure drop and mechanical power
        delta_p = friction_coefficient * (self.fluid_density * fluid_velocity**2) / 2
        friction_power = delta_p * main_pipe_mass_flow_rate / self.fluid_density
        return friction_power

    def forward(self):
        #TODO: Implement the forward
        pass
