import numpy as np
import torch
import torch.nn as nn

from xitorch.optimize import rootfinder
from loguru import logger


class VoltageModel(nn.Module):

    def __init__(
        self,
        num_cells_in_series: int,
        num_cells_in_strings: int,
        dt_hr: torch.Tensor | float,
        resistance: torch.Tensor | float = 0.09,
        Vfull: torch.Tensor | float = 4.2,
        Vexp: torch.Tensor | float = 3.53,
        Vnom: torch.Tensor | float = 3.42,
        Qfull: torch.Tensor | float = 3.2,
        Qexp: torch.Tensor | float = 0.8075 * 3.2,
        Qnom: torch.Tensor | float = 0.976875 * 3.2,
        C_rate: torch.Tensor | float = 1.0
    ):
        super().__init__()
        # voltage parameters
        self.num_cells_series = num_cells_in_series
        self.num_strings = num_cells_in_strings
        self.resistance = resistance
        self.dt_hr = dt_hr
        self.Vfull = torch.tensor([Vfull]) if isinstance(Vfull, float) else Vfull
        self.Vexp = torch.tensor([Vexp]) if isinstance(Vexp, float) else Vexp
        self.Vnom = torch.tensor([Vnom]) if isinstance(Vnom, float) else Vnom
        self.Qfull = torch.tensor([Qfull]) if isinstance(Qfull, float) else Qfull
        self.Qexp = torch.tensor([Qexp]) if isinstance(Qexp, float) else Qexp
        self.Qnom = torch.tensor([Qnom]) if isinstance(Qnom, float) else Qnom
        self.C_rate = torch.tensor([C_rate]) if isinstance(C_rate, float) else C_rate
        # voltage state
        self.cell_voltage = None
        self.soc = None
        self._A = None
        self._B0 = None
        self._K = None
        self._E0 = None
        self.parameter_compute()

    def parameter_compute(self):
        """
        Compute the voltage model parameters based on the given voltage model parameters.
        Reference: Tremblay 2009 "A Generic Bettery Model for the Dynamic Simulation of Hybrid Electric Vehicles" Page 2
        """
        I = self.Qfull * self.C_rate
        self._A = self.Vfull - self.Vexp
        self._B0 = 3. / self.Qexp
        self._K = (
            (self.Vfull - self.Vnom + self._A * (torch.exp(-self._B0 * self.Qnom) - 1)) *
            (self.Qfull - self.Qnom)
        ) / self.Qnom
        self._E0 = self.Vfull + self._K + self.resistance * I - self._A

        if self._A < 0 or self._B0 < 0 or self._K < 0 or self._E0 < 0:
            raise logger.critical(
                "Error during calculation of battery voltage model parameters: negative value(s) found.\n"
                f"A: {self._A}, B: {self._B0}, K: {self._K}, E0: {self._E0}"
            )

    def compute_voltage(self, Q_cell: torch.Tensor, q0_cell: torch.Tensor, I: torch.Tensor):
        it = Q_cell - q0_cell
        E = self._E0 - self._K * (Q_cell / (Q_cell - it)) + self._A * torch.exp(-self._B0 * it)
        return E - self.resistance * I

    def calculate_voltage_for_current(self, I: torch.Tensor, q: torch.Tensor, q_max: torch.Tensor):
        voltage_per_series = torch.maximum(self.compute_voltage(q, q_max, I), 0.0)
        return self.num_cells_series * voltage_per_series

    def update_voltage(self, q: torch.Tensor, qmax: torch.Tensor, I: torch.Tensor):
        qmax /= self.num_strings
        q /= self.num_strings
        I /= self.num_strings
        self.cell_voltage = torch.maximum(self.compute_voltage(q, qmax, I), 0.0)

    def calculate_max_charge_w(self, q: torch.Tensor, qmax: torch.Tensor):
        q /= self.num_strings
        qmax /= self.num_strings
        I = (q - qmax) / self.dt_hr
        return I * self.compute_voltage(qmax, I, qmax) * self.num_strings * self.num_cells_series

    def calculate_max_discharge_w(self, q: torch.Tensor, qmax: torch.Tensor):
        q /= self.num_strings
        qmax /= self.num_strings
        current = q * 0.5
        vol = 0
        incr = q / 10
        max_p = 0
        max_I = 0
        while current * self.dt_hr < q and vol >= 0:
            vol = self.compute_voltage(qmax, current, q - current * self.dt_hr)
            p = current * vol
            if p > max_p:
                max_p = p
                max_I = current
            current += incr
        current = max_I
        maxI = current * self.num_strings
        return max_p * self.num_strings * self.num_cells_series

    def calculate_current_for_target_w(
        self,
        P_watts: torch.Tensor | float,
        q: torch.Tensor | float,
        qmax: torch.Tensor | float
    ):
        if P_watts == 0:
            return 0.0

        target_power_per_cell = torch.abs(P_watts) / (self.num_cells_series * self.num_strings)
        current_charge_per_string = q / self.num_strings
        max_charge_per_string = qmax / self.num_strings

        def solve_current_for_discharge_power(I: torch.Tensor):
            V = (
                self._E0 - self._K * max_charge_per_string / (current_charge_per_string - I * self.dt_hr) +
                self._A * torch.exp(-self._B0 * (max_charge_per_string - (current_charge_per_string - I * self.dt_hr)))-
                self.resistance * I
            )
            return I * V - target_power_per_cell

        def solve_current_for_charge_power(I: torch.Tensor):
            V = (
                self._E0 - self._K * max_charge_per_string / (current_charge_per_string + I * self.dt_hr) +
                self._A * torch.exp(-self._B0 * (max_charge_per_string - (current_charge_per_string + I * self.dt_hr)))-
                self.resistance * I
            )
            return I * V - target_power_per_cell

        if P_watts > 0:
            f = solve_current_for_charge_power
        else:
            f = solve_current_for_discharge_power

        direction = 1.0 if P_watts > 0 else -1.0

        if self.cell_voltage is not None:
            x = torch.tensor([target_power_per_cell / self.cell_voltage * self.dt_hr], dtype=torch.float64)
        else:
            x = torch.tensor([target_power_per_cell / self.Vnom * self.dt_hr], dtype=torch.float64)
        # find the current that satisfies the power demand
        x = rootfinder(
            fcn=f,
            y0=x
        )
        return x * self.num_strings * direction


if __name__ == "__main__":
    model = VoltageModel(
        num_cells_in_series=139,
        num_cells_in_strings=1,
        dt_hr=1
    )
    model.calculate_current_for_target_w(
        P_watts=torch.tensor(10000.),
        q=model.Qfull,
        qmax=model.Qfull
    )
