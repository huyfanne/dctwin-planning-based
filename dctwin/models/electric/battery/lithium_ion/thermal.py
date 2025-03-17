from typing import Optional
import numpy as np
import torch
from torch import nn


class ThermalModel(nn.Module):

    def __init__(
        self,
        dt_hr: float | torch.Tensor,
        mass: float | torch.Tensor,
        surface_area: float | torch.Tensor,
        Cp: float | torch.Tensor,
        h: float | torch.Tensor,
        resistance: float | torch.Tensor,
        T_room_init: float | torch.Tensor
    ):
        super().__init__()
        # thermal parameters
        self.dt_hr = dt_hr if isinstance(dt_hr, torch.Tensor) else torch.tensor(dt_hr)
        self.dt_sec = dt_hr * 3600
        self.mass = mass if isinstance(mass, torch.Tensor) else torch.tensor(mass)
        self.surface_area = surface_area if isinstance(surface_area, torch.Tensor) else torch.tensor(surface_area)
        self.Cp = Cp if isinstance(Cp, torch.Tensor) else torch.tensor(Cp)
        self.h = h if isinstance(h, torch.Tensor) else torch.tensor(h)
        self.resistance = resistance if isinstance(resistance, torch.Tensor) else torch.tensor(resistance)
        self.T_room_init = T_room_init if isinstance(T_room_init, torch.Tensor) else torch.tensor(T_room_init)
        # thermal state
        self.T_batt = T_room_init
        self.T_room = T_room_init
        self.T_batt_prev = T_room_init
        self.heat_dissipated = 0.0

    def update_battery_temperature(
        self,
        I: torch.Tensor | float,
        T_room: Optional[torch.Tensor] = None
    ):
        """
        Update the battery temperature based on the input current and the previous temperature with the thermodynamics
        model. The instantaneous heat source is P_heat = I^2 * R, where R is the internal resistance of the battery.
        The thermodynamics model is based on the following equation:

                            dT_{batt}/dt = (hA(T_room - T_{batt}) + I^2 * R) / (mass * Cp)

        """
        if T_room is not None:
            self.T_room = T_room
        # first calculate the steady-state battery temperature
        T_steady_state = I * I * self.resistance / (self.surface_area * self.h) + self.T_room
        # calculate the time constant for the transient solution
        diffusion = torch.exp(-self.surface_area * self.h * self.dt_sec / self.mass / self.Cp)
        coeff_avg = self.mass * self.Cp / self.surface_area / self.h / self.dt_sec
        # get the battery temperature with the transient solution by providing the dt
        self.T_batt = (self.T_batt_prev - T_steady_state) * coeff_avg * (1 - diffusion) + T_steady_state
        # calculate the convective heat dissipated to the environment at the end of the time step
        self.heat_dissipated = (self.T_batt - self.T_room) * self.surface_area * self.h / 1000.
        # update temp for use in next timestep
        self.T_batt_prev = (self.T_batt_prev - T_steady_state) * diffusion + T_steady_state

    @property
    def state(self):
        return {
            "q_relative_thermal": self.q_relative_thermal,
            "T_batt": self.T_batt,
            "T_room": self.T_room,
            "heat_dissipated": self.heat_dissipated,
            "T_batt_prev": self.T_batt_prev
        }
