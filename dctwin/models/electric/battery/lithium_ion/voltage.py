import numpy as np
import torch
import torch.nn as nn
from scipy.optimize import root

from loguru import logger


class VoltageModel(nn.Module):

    def __init__(
        self,
        num_cells_in_series: int,
        num_cells_in_strings: int,
        Vnom_default: torch.Tensor | float,
        resistance: torch.Tensor | float,
        dt_hr: torch.Tensor | float,
        Vfull: torch.Tensor | float,
        Vexp: torch.Tensor | float,
        Vnom: torch.Tensor | float,
        Qfull: torch.Tensor | float,
        Qexp: torch.Tensor | float,
        Qnom: torch.Tensor | float,
        C_rate: torch.Tensor | float,
    ):
        super().__init__()
        # voltage parameters
        self.num_cells_series = num_cells_in_series
        self.num_strings = num_cells_in_strings
        self.Vnom_default = Vnom_default
        self.resistance = resistance
        self.dt_hr = dt_hr
        self.Vfull = Vfull
        self.Vexp = Vexp
        self.Vnom = Vnom
        self.Qfull = Qfull
        self.Qexp = Qexp
        self.Qnom = Qnom
        self.C_rate = C_rate
        # voltage state
        self.cell_voltage = 0.0
        self.soc = 0.0
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

    def solve_current_for_discharge_power(self, I: torch.Tensor, target_power_per_cell: torch.Tensor):
        V = (
            self._E0 - self._K * self.solver_Q / (self.solver_q - I * self.dt_hr) +
            self._A * torch.exp(-self._B0 * (self.solver_Q - (self.solver_q - I * self.dt_hr))) -
            self.resistance * I
        )
        return I * V - target_power_per_cell

    def solve_current_for_charge_power(self, I: torch.Tensor, target_power_per_cell: torch.Tensor):
        V = (
            self._E0 - self._K * self.solver_Q / (self.solver_q + I * self.dt_hr) +
            self._A * torch.exp(-self._B0 * (self.solver_Q - (self.solver_q + I * self.dt_hr))) -
            self.resistance * I
        )
        return I * V - target_power_per_cell

    def calculate_current_for_target_w(
        self,
        P_watts: torch.Tensor | float,
        q: torch.Tensor | float,
        qmax: torch.Tensor | float,
        T_battery: torch.Tensor | float
    ):
        if P_watts == 0:
            return 0.0

        target_power_per_cell = torch.abs(P_watts) / (self.num_cells_series * self.num_strings)

        def f(
            I: torch.Tensor
        ):
            if P_watts > 0:
                return self.solve_current_for_discharge_power(I, target_power_per_cell)
            else:
                return self.solve_current_for_charge_power(I, target_power_per_cell)

        direction = 1.0 if P_watts > 0 else -1.0
        x = torch.tensor([self.solver_power / self.cell_voltage * self.dt_hr], dtype=torch.float64)
        # find the current that satisfies the power demand
        x = root(
            fun=f,
            x0=np.ndarray.flatten(x.detach().numpy()),
        )
        x = torch.from_numpy(x)
        return x[0] * self.num_strings * direction
