from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from loguru import logger
import matplotlib.pyplot as plt

from capacity import CapacityModel
from voltage import VoltageModel
from thermal import ThermalModel
from lifetime import NMCLifetimeModel


class LithiumIonBattery(nn.Module):
    """
    Lithium-Ion battery model based on SAM library.
    """

    def __init__(
        self,
        num_cells_in_series: int,
        num_cells_in_strings: int,
        initial_fractional_state_of_charge: float,
        battery_mass: float,
        battery_surface_area: float,
        battery_specific_heat_capacity: float,
        heat_transfer_coefficient_between_battery_and_ambient: float,
        T_room_init: float = 20.0,
        dc_to_dc_charging_efficiency: float = 0.95,
        dt_hr: float = 1.0,
        resistance: torch.Tensor | float = 0.09,
        Vfull: torch.Tensor | float = 4.2,
        Vexp: torch.Tensor | float = 3.53,
        Vnom: torch.Tensor | float = 3.42,
        Qfull: torch.Tensor | float = 3.2,
        Qexp: torch.Tensor | float = 0.8075 * 3.2,
        Qnom: torch.Tensor | float = 0.976875 * 3.2,
        C_rate: torch.Tensor | float = 0.2,
    ):
        super().__init__()
        self.capacity_model = CapacityModel(
            q_max=Qfull,
            initial_soc=initial_fractional_state_of_charge,
            min_soc=0.0,
            max_soc=100.0,
            dt_hr=dt_hr,
        )
        self.voltage_model = VoltageModel(
            num_cells_in_series=num_cells_in_series,
            num_cells_in_strings=num_cells_in_strings,
            dt_hr=dt_hr,
            resistance=resistance,
            Vfull=Vfull,
            Vexp=Vexp,
            Vnom=Vnom,
            Qfull=Qfull,
            Qexp=Qexp,
            Qnom=Qnom,
            C_rate=C_rate,
        )
        self.thermal_model = ThermalModel(
            dt_hr=dt_hr,
            mass=battery_mass,
            surface_area=battery_surface_area,
            Cp=battery_specific_heat_capacity,
            h=heat_transfer_coefficient_between_battery_and_ambient,
            resistance=resistance * num_cells_in_series / num_cells_in_strings,
            T_room_init=T_room_init
            if isinstance(T_room_init, torch.Tensor)
            else torch.tensor(T_room_init),
        )
        self.lifetime_model = NMCLifetimeModel(
            dt_hr=dt_hr,
        )

        # battery states
        self.dc_to_dc_charging_efficiency = dc_to_dc_charging_efficiency
        self.V = torch.zeros(1)
        self.Q = torch.tensor(Qfull * initial_fractional_state_of_charge)
        self.Q_max = torch.tensor(Qfull)
        self.I = torch.zeros(1)
        self.P = torch.zeros(1)
        self.max_discharge_P, self.max_discharge_I = (
            self.calculate_max_discharge_power_kw()
        )
        self.max_charge_P, self.max_charge_I = self.calculate_max_charge_power_kw()
        self.lifetime_counter = torch.zeros(1)

    def calculate_current_for_power_kw(self, power_kw: torch.Tensor):
        """
        Calculate the current based on the input power in kW.
        """
        if power_kw == 0:
            return torch.zeros(1), torch.zeros(1)
        if power_kw < 0.0:  # charging
            max_power, current = self.calculate_max_charge_power_kw()
            if max_power > power_kw:
                logger.warning(
                    f"Charging power {abs(power_kw.item())} kW exceeds the power limit {abs(max_power.item())} kW"
                )
                power_kw = max_power
                return power_kw, current
        else:  # discharge
            max_power, current = self.calculate_max_discharge_power_kw()
            if max_power < power_kw:
                logger.warning(
                    f"Discharging power {abs(power_kw.item())} kW exceeds the power limit {abs(max_power.item())} kW"
                )
                power_kw = max_power
                return power_kw, current
        return self.voltage_model.calculate_current_for_target_w(
            P_watts=power_kw * 1000.0,
            q=self.capacity_model.q0,
            q_max=self.capacity_model.q_max,
        )

    def calculate_voltage_for_current(self, I: torch.Tensor | float):
        """
        Calculate the voltage based on the input current.
        """
        return self.voltage_model.calculate_voltage_for_current(
            I=I,
            q=self.capacity_model.q0,
            q_max=self.capacity_model.q_max,
        )

    def calculate_max_discharge_power_kw(self):
        """
        Calculate the maximum discharge power in kW.
        """
        max_discharge_power, max_I = self.voltage_model.calculate_max_discharge_w(
            q=self.capacity_model.q0, q_max=self.capacity_model.q_max
        )
        return max_discharge_power * 0.001, max_I

    def calculate_max_charge_power_kw(self):
        """
        Calculate the maximum charge power in kW.
        """
        max_charge_power, max_I = self.voltage_model.calculate_max_charge_w(
            q=self.capacity_model.q0, q_max=self.capacity_model.q_max
        )
        return max_charge_power * 0.001, max_I

    def run_thermal_model(self, I: torch.Tensor | float):
        return self.thermal_model.update_battery_temperature(I)

    def run_capacity_model(self, I: torch.Tensor | float):
        return self.capacity_model.update_capacity(I=I)

    def run_voltage_model(self, I: torch.Tensor | float):
        return self.voltage_model.update_voltage(
            q=self.capacity_model.q0 - I * self.voltage_model.dt_hr,
            q_max=self.capacity_model.q_max,
            I=I,
        )

    def run_lifetime_model(self):
        return self.lifetime_model.run(
            charge_changed=self.capacity_model.change_mode,
            prev_dod=self.capacity_model.prev_dod,
            dod=self.capacity_model.dod,
            T_battery=self.thermal_model.T_batt,
        )

    def update_state(self, I: torch.Tensor | float):
        self.I = I
        self.Q = self.capacity_model.q0
        self.Q_max = self.capacity_model.q_max
        self.V = self.voltage_model.cell_voltage * self.voltage_model.num_cells_series
        self.max_discharge_P, self.max_discharge_I = (
            self.calculate_max_discharge_power_kw()
        )
        self.max_charge_P, self.max_charge_I = self.calculate_max_charge_power_kw()
        self.P = I * self.V * 0.001  # convert to kW

    def forward(
        self,
        P_kw: Optional[torch.Tensor | float] = None,
        I: Optional[torch.Tensor | float] = None,
        T_room: torch.Tensor | float = None,
    ):
        # fixed power charge/discharge mode
        if I is None:
            # calculate the battery cell current based on the demanded power
            _, I = self.calculate_current_for_power_kw(P_kw)
        # calculate the new battery temperature based on the current
        self.thermal_model.update_battery_temperature(I, T_room)
        # run the voltage model to calculate the battery terminal voltage given the current
        self.run_voltage_model(I)
        # run the capacity model to update the battery charge capacity given the charge current
        self.run_capacity_model(I)
        # update the lifetime model and losses model
        self.run_lifetime_model()
        # update all electrical states
        self.update_state(I)


if __name__ == "__main__":
    model = LithiumIonBattery(
        num_cells_in_series=198,
        num_cells_in_strings=2,
        initial_fractional_state_of_charge=100.0,
        battery_mass=342.0,
        battery_surface_area=4.26,
        battery_specific_heat_capacity=1500.0,
        heat_transfer_coefficient_between_battery_and_ambient=7.5,
        dc_to_dc_charging_efficiency=0.95,
        dt_hr=1.0 / 10,
        C_rate=0.2,
    )

    """
    # Fixed power discharge
    I = torch.tensor([.5])
    total_time = 1 / (model.voltage_model.C_rate / 10)
    res_soc = []
    res_power = []
    res_voltage = []
    for i in range(int(total_time.item())):
        model.forward(
            P_kw=None,
            I=I
        )
        res_soc.append(model.capacity_model.soc)
        res_voltage.append(model.V)
        res_power.append(model.P*1000)
    res_voltage = torch.stack(res_voltage).view(-1)
    res_power = torch.stack(res_power).view(-1)
    res_soc = torch.stack(res_soc).view(-1)

    t = torch.arange(0, total_time.item(), model.voltage_model.dt_hr)

    plt.figure(dpi=300)
    plt.subplot(311)
    plt.title(f"Fixed Discharge Current: {I.item():.1f} A")
    plt.plot(res_voltage, label="Voltage [V]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("Voltage [V]")
    plt.legend()

    plt.subplot(312)
    plt.plot(res_power, label="Power [kW]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("Power [W]")
    plt.legend()

    plt.subplot(313)
    plt.plot(res_soc, label="SOC [%]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("SOC [%]")

    plt.legend()
    plt.show()
    plt.savefig("/home/ztw/dctwin/dctwin/models/electric/battery/lithium_ion/plot.png")

    # Fixed power discharge
    model = LithiumIonBattery(
        num_cells_in_series=100,
        num_cells_in_strings=1,
        initial_fractional_state_of_charge=100.,
        battery_mass=342.,
        battery_surface_area=4.26,
        battery_specific_heat_capacity=1500.,
        heat_transfer_coefficient_between_battery_and_ambient=7.5,
        dc_to_dc_charging_efficiency=0.95,
        dt_hr=1.0/10,
        C_rate=0.2
    )
    P_kw = torch.tensor(0.005)
    total_time = 1 / (model.voltage_model.C_rate / 5)
    res_soc = []
    res_power = []
    res_voltage = []
    for i in range(int(total_time.item())):
        model.forward(
            P_kw=P_kw,
            I=None
        )
        logger.info(
            f"Voltage: {model.V.item():.3f}, "
            f"Power: {model.P.item()*1000:.3f}, "
            f"SOC: {model.capacity_model.soc.item():.3f}, "
            f"I: {model.I.item():.3f},"
            #f"Lifetime (Q_relative): {model.lifetime_model.q_relative:.3f}"
        )
        if model.capacity_model.soc < 1e-3:
            break
        res_soc.append(model.capacity_model.soc)
        res_voltage.append(model.V)
        res_power.append(model.P*1000)
    res_voltage = torch.stack(res_voltage).view(-1)
    res_power = torch.stack(res_power).view(-1)
    res_soc = torch.stack(res_soc).view(-1)

    t = torch.arange(0, total_time.item(), model.voltage_model.dt_hr)

    plt.figure(dpi=300)
    plt.subplot(311)
    plt.title(f"Fixed Discharge Power: {P_kw.item()*1000:.1f} W")
    plt.plot(res_voltage[:-1], label="Voltage [V]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("Voltage [V]")
    plt.legend()

    plt.subplot(312)
    plt.plot(res_power[:-1], label="Power [W]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("Power [W]")
    plt.ylim(0, 10)
    plt.legend()

    plt.subplot(313)
    plt.plot(res_soc[:-1], label="SOC [%]")
    plt.grid(axis="y")
    plt.xlabel("Time [s]")
    plt.ylabel("SOC [%]")

    plt.legend()
    plt.show()
"""

    def simulate_battery_cycle(
        model: LithiumIonBattery,
        discharge_power_kw: float | torch.Tensor,
        charge_power_kw: float | torch.Tensor,
        total_time_discharge: float | torch.Tensor,
        total_time_charge: float | torch.Tensor,
        num_cycles: int,
    ):
        # Arrays to store results
        res_soc = []
        res_power = []
        res_voltage = []
        res_time = []

        current_time = 0.0  # Initialize time tracking

        for cycle in range(num_cycles):
            # Discharge Phase
            for _ in range(int(total_time_discharge)):
                model.forward(P_kw=torch.tensor(discharge_power_kw))  # Discharging
                res_soc.append(model.capacity_model.soc.item())
                res_voltage.append(model.V.item())
                res_power.append(model.P.item() * 1000)  # Convert kW to Watts
                res_time.append(current_time)
                current_time += model.voltage_model.dt_hr

            # Charge Phase
            for _ in range(int(total_time_charge)):
                model.forward(P_kw=torch.tensor(-charge_power_kw))  # Charging
                res_soc.append(model.capacity_model.soc.item())
                res_voltage.append(model.V.item())
                res_power.append(model.P.item() * 1000)  # Convert kW to Watts
                res_time.append(current_time)
                current_time += model.voltage_model.dt_hr

        return res_soc, res_power, res_voltage, res_time

    # Define the simulation parameters
    discharge_power_kw = 0.005  # kW
    charge_power_kw = 0.004  # kW
    total_time_discharge = 1 / (model.voltage_model.C_rate / 10)
    total_time_charge = 1 / (model.voltage_model.C_rate / 10)
    num_cycles = 10  # Number of complete discharge-charge cycles

    # Run simulation
    res_soc, res_power, res_voltage, res_time = simulate_battery_cycle(
        model=model,
        discharge_power_kw=discharge_power_kw,
        charge_power_kw=charge_power_kw,
        total_time_discharge=total_time_discharge,
        total_time_charge=total_time_charge,
        num_cycles=num_cycles,
    )

    # Plotting results
    time_steps = np.arange(len(res_soc)) * model.voltage_model.dt_hr  # Time in hours

    plt.figure(dpi=300)
    plt.subplot(311)
    plt.title("Battery Cycle: Discharge followed by Charge")
    plt.plot(time_steps, res_voltage, label="Voltage [V]")
    plt.grid(True)
    plt.xlabel("Time [h]")
    plt.ylabel("Voltage [V]")
    plt.legend()

    plt.subplot(312)
    plt.plot(time_steps, res_power, label="Power [W]")
    plt.grid(True)
    plt.xlabel("Time [h]")
    plt.ylabel("Power [W]")
    plt.legend()

    plt.subplot(313)
    plt.plot(time_steps, res_soc, label="SOC [%]")
    plt.grid(True)
    plt.xlabel("Time [h]")
    plt.ylabel("SOC [%]")
    plt.legend()

    plt.tight_layout()
    plt.show()
    plt.savefig(
        "/home/ztw/dctwin/dctwin/models/electric/battery/lithium_ion/plot_chargedischarge.png"
    )
