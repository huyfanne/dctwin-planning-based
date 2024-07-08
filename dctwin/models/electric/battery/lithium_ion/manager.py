from typing import Dict, Any
import torch
import torch.nn as nn

from .capacity import CapacityModel
from .voltage import VoltageModel
from .thermal import ThermalModel
from .lifetime import NMCLifetimeModel


class LithiumIonBattery(nn.Module):

    def __init__(
        self,
        num_cells_in_series: int,
        num_cells_in_strings: int,
        initial_fractional_state_of_charge: float,
        dc_to_dc_charging_efficiency: float,
        battery_mass: float,
        battery_surface_area: float,
        battery_specific_heat_capacity: float,
        heat_transfer_coefficient_between_battery_and_ambient: float,
        dt_hr: float = 1.0,
    ):
        super().__init__()
        self.capacity_model = CapacityModel(
            qmax_init=1.0,
            qmax=1.0,
            initial_soc=initial_fractional_state_of_charge,
            min_soc=0.0,
            max_soc=1.0,
            dt_hr=dt_hr
        )
        self.voltage_model = VoltageModel(
            num_cells_in_series=num_cells_in_series,
        )
        self.thermal_model = ThermalModel()
        self.lifetime_model = NMCLifetimeModel()

        # battery states
        self.V = torch.zeros(1)
        self.Q = torch.zeros(1)
        self.Q_max = torch.zeros(1)
        self.I = torch.zeros(1)
        self.P = torch.zeros(1)
        self.P_dischargable = torch.zeros(1)
        self.P_chargeable = torch.zeros(1)
        self.lifetime_counter = torch.zeros(1)

    def calculate_current_for_power_kw(self, power_kw: torch.Tensor) -> torch.Tensor:
        """
        Calculate the current based on the input power in kW.
        """
        if power_kw == 0:
            return torch.zeros(1)
        if power_kw < 0.:  # charging
            max_power, current = self.calculate_max_charge_kw()
            if max_power > power_kw:
                power_kw = max_power
                return current
        else:  # discharge
            max_power, current = self.calculate_max_discharge_kw()
            if max_power < power_kw:
                power_kw = max_power
                return current
        return self.voltage_model.calculate_current_for_target_w(
            P_watts=power_kw * 1000.,
            q=self.capacity_model.q0,
            qmax=torch.minimum(self.capacity_model.qmax, self.capacity_model.qmax_thermal),
            T_battery=self.thermal_model.T_batt
        )

    def calculate_voltage_for_current(self, I: torch.Tensor | float):
        """
        Calculate the voltage based on the input current.
        """
        return self.voltage_model.calculate_voltage_for_current(
            I=I,
            q=self.capacity_model.q0,
            q_max=torch.minimum(self.capacity_model.qmax, self.capacity_model.qmax_thermal),
        )

    def calculate_max_charge_kw(self):
        q = self.capacity_model.q0
        soc = self.capacity_model.max_soc * 0.01
        qmax = self.capacity_model.qmax * soc
        power_w = 0
        current = 0
        its = 0
        while (
            torch.abs(
                power_w - self.voltage_model.calculate_max_charge_w(q, qmax)
            ) > 1e-7 and its < 10
        ):
            power_w = self.voltage_model.calculate_max_charge_w(q, qmax)
            self.thermal_model.update_battery_temperature(current)
            qmax = self.capacity_model.qmax * self.thermal_model.capacity_percent * 0.01 * soc
            its += 1
        return power_w / 1000., current

    def run_thermal_model(self, I: torch.Tensor | float):
        return self.thermal_model.update_battery_temperature(I)

    def run_capacity_model(self, I: torch.Tensor | float):
        return self.capacity_model.update_capacity(I, dt_hr=self.dt_hr)

    def run_voltage_model(self, I: torch.Tensor | float):
        return self.voltage_model.update_voltage(
            q=self.capacity_model.q0,
            qmax=torch.minimum(self.capacity_model.qmax, self.capacity_model.qmax_thermal),
            I=I
        )

    def run_lifetime_model(self):
        return self.lifetime_model.run(
            charge_changed=self.capacity_model.change_mode,
            prev_dod=self.capacity_model.prev_dod,
            dod=self.capacity_model.dod,
            T_battery=self.thermal_model.T_batt
        )

    def update_state(self, I: torch.Tensor | float):
        self.I = I
        self.Q = self.capacity_model.q0
        self.Q_max = self.capacity_model.qmax
        self.V = self.voltage_model.cell_voltage
        self.P_dischargable = self.calculate_max_discharge_kw()
        self.P_chargeable = self.calculate_max_charge_kw()
        self.P = I * self.voltage_model.cell_voltage * 0.001  # convert to kW

    def forward(self, P_kw: torch.Tensor | float):
        # calculate the battery cell current based on the demanded power
        I = self.calculate_current_for_power_kw(P_kw)
        # run the voltage model to calculate the battery terminal voltage given the current
        self.run_voltage_model(I)
        # update the lifetime model and losses model
        self.run_lifetime_model()
        self.update_state(I)
