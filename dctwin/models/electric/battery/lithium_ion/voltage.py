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

    def compute_voltage(
        self,
        q_max: torch.Tensor,
        q: torch.Tensor,
        I: torch.Tensor
    ):
        it = q_max - q
        E = self._E0 - self._K * (q_max / (q_max - it)) + self._A * torch.exp(-self._B0 * it)
        return E - self.resistance * I

    def calculate_voltage_for_current(
        self,
        I: torch.Tensor,
        q: torch.Tensor,
        q_max: torch.Tensor
    ):
        voltage_per_series = torch.relu(
            self.compute_voltage(
                q_max=q_max,
                q=q,
                I=I
            )
        )
        return self.num_cells_series * voltage_per_series

    def update_voltage(self, q: torch.Tensor, q_max: torch.Tensor, I: torch.Tensor):
        q_max /= self.num_strings
        q /= self.num_strings
        I /= self.num_strings
        self.cell_voltage = torch.relu(
            self.compute_voltage(q_max=q_max, q=q, I=I)
        )

    def calculate_max_charge_w(self, q: torch.Tensor, q_max: torch.Tensor):
        """
        Calculate the maximum power that can be charged into the battery.
        Method: Assuming constant current charge over dt_hr time interval, we first determine the charging current
        with the current charge q and the maximum charge q_max. Then, we calculate voltage with the constant current.
        Finally, we calculate the power with the voltage and the current.

        :param q: Current charge of the battery [unit: Ah]
        :param q_max: Maximum charge of the battery [unit: Ah]
        """
        q /= self.num_strings
        q_max /= self.num_strings
        I = (q - q_max) / self.dt_hr
        max_charge_power = I * self.compute_voltage(q_max, q, I) * self.num_strings * self.num_cells_series
        return max_charge_power, I * self.num_strings

    def calculate_max_discharge_w(self, q: torch.Tensor, q_max: torch.Tensor):
        """
        Calculate the maximum power that can be discharged from the battery.
        Method: We first determine the current charge and maximum charge per string. Then, we use grid search to find
        the optimum current that maximizes the power output. Finally, we calculate the power with the optimum current.
        The power is calculated in a per-cell basis. Hence, it should be multiplied by the number of cells.
        """
        q /= self.num_strings
        q_max /= self.num_strings
        I = q * 0.5  # initial current
        vol = 0
        incr = q / 200
        max_p = 0
        max_I = I
        # solve the optimum current I that maximizes the power output with grid search
        while I * self.dt_hr < q and vol >= 0:
            V = self.compute_voltage(
                q_max=q_max,
                q=q - I * self.dt_hr,
                I=I
            )
            p = I * V
            if p > max_p:
                max_p = p
                max_I = I
            I += incr
        return max_p * self.num_strings * self.num_cells_series, max_I * self.num_strings

    def calculate_current_for_target_w(
        self,
        P_watts: torch.Tensor | float,
        q: torch.Tensor | float,
        q_max: torch.Tensor | float
    ):
        """
        Calculate the current for the target power in watts given the current charge and maximum available charge.
        Method: We first determine the target power per cell. Then, we solve the current for the target power
        with the given current charge and maximum charge using differentiable root finding solver from xitorch.
        """
        if P_watts == 0:
            return 0.0

        target_power_per_cell = torch.abs(P_watts) / (self.num_cells_series * self.num_strings)
        current_charge_per_string = q / self.num_strings
        max_charge_per_string = q_max / self.num_strings

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

        # find the current that satisfies the power demand with differentiable root finding function in xitorch library
        x = rootfinder(
            fcn=f,
            y0=x
        )
        return x * self.num_strings * direction


if __name__ == "__main__":
    model = VoltageModel(
        num_cells_in_series=139,
        num_cells_in_strings=25,
        dt_hr=1
    )
    p_dischargable, _ = model.calculate_max_discharge_w(
        q=model.Qfull,
        q_max=model.Qfull
    )
    logger.info(
        f"Maximum discharge power: {p_dischargable.item():.3f} W"
    )
    p = torch.tensor(-1000.)
    I = model.calculate_current_for_target_w(
        P_watts=p,
        q=model.Qfull,
        q_max=model.Qfull
    )
    logger.info(
        f"Charged power: {p.item():.3f} W, Charged Current: {I.item(): 2f} A"
    )
