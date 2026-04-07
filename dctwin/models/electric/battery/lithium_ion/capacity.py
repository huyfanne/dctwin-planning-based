import torch
import torch.nn as nn


class ChargeMode:
    NO_CHARGE = 0
    CHARGE = 1
    DISCHARGE = 2


class CapacityModel(nn.Module):
    def __init__(
        self,
        q_max: torch.Tensor | float,
        initial_soc: torch.Tensor | float,
        min_soc: torch.Tensor | float = 0.0,
        max_soc: torch.Tensor | float = 100.0,
        dt_hr: torch.Tensor | float = 1.0,
    ):
        super().__init__()
        # capacity parameters
        self.q_max = q_max if isinstance(q_max, torch.Tensor) else torch.tensor(q_max)
        self.q_max_init = (
            q_max if isinstance(q_max, torch.Tensor) else torch.tensor(q_max)
        )
        self.initial_soc = (
            initial_soc
            if isinstance(initial_soc, torch.Tensor)
            else torch.tensor(initial_soc)
        )
        self.min_soc = (
            min_soc if isinstance(min_soc, torch.Tensor) else torch.tensor(min_soc)
        )
        self.max_soc = (
            max_soc if isinstance(max_soc, torch.Tensor) else torch.tensor(max_soc)
        )
        self.dt_hr = dt_hr if isinstance(dt_hr, torch.Tensor) else torch.tensor(dt_hr)
        # capacity state
        # [Ah] - Total capacity at current timestep
        self.q0 = self.q_max * initial_soc / 100.0
        # [Ah] - Maximum capacity considering lifetime degradation at current timestep
        self.q_max_lifetime = (
            q_max if isinstance(q_max, torch.Tensor) else torch.tensor(q_max)
        )
        # [A] - Cell current at current timestep
        self.cell_current = torch.zeros(1)
        # [A] - Cell current loss at current timestep
        self.I_losses = torch.zeros(1)
        # [0 - 100%] - State of charge (SOC) at current timestep
        self.soc = (
            initial_soc
            if isinstance(initial_soc, torch.Tensor)
            else torch.tensor(initial_soc)
        )
        # [0 - 100%] - State of charge (SOC) at previous timestep
        self.soc_prev = initial_soc
        # Charge mode at current timestep
        self.charge_mode = ChargeMode.NO_CHARGE
        # Charge mode at previous timestep
        self.prev_charge = -1
        # indicates if the charge mode has changed
        self.change_mode = False
        # algorithmic parameters
        self.tol = 0.002
        # Initialize with a default value, e.g., None or a starting DOD value
        self.prev_dod = None
        self.dod = 50

    def check_soc(self):
        q_upper = self.q_max_lifetime * self.max_soc * 0.01
        q_lower = self.q_max_lifetime * self.min_soc * 0.01

        if self.q0 > q_upper + self.tol:
            if self.cell_current < -self.tol:
                self.cell_current += (self.q0 - q_upper) / self.dt_hr
                self.cell_current = torch.minimum(torch.zeros(1), self.cell_current)
            self.q0 = q_upper
        elif self.q0 < q_lower - self.tol:
            if self.cell_current > self.tol:
                self.cell_current += (self.q0 - q_lower) / self.dt_hr
                self.cell_current = torch.maximum(torch.zeros(1), self.cell_current)
            self.q0 = q_lower

    def check_charge_change(self):
        """
        Check if the charge mode has changed. This is used to calculate the lifetime degradation as it is related to
        the number of cycles.
        """
        self.charge_mode = ChargeMode.NO_CHARGE
        if self.cell_current < 0:
            self.charge_mode = ChargeMode.CHARGE
        elif self.cell_current > 0:
            self.charge_mode = ChargeMode.DISCHARGE

        self.change_mode = False
        if (
            self.charge_mode != self.prev_charge
            and self.charge_mode != ChargeMode.NO_CHARGE
            and self.prev_charge != ChargeMode.NO_CHARGE
        ):
            self.change_mode = True
            self.prev_charge = self.charge_mode

    def update_soc(self):
        """
        Update the state of charge based on the current available charge q0.
        """
        if self.q_max == 0:
            self.q0 = torch.zeros(1)
            self.soc = torch.zeros(1)
            return
        if self.q0 > self.q_max:
            self.q0 = self.q_max
        if self.q_max > 0:
            self.soc = 100.0 * (self.q0 / self.q_max)
        else:
            self.soc = 0.0

        if self.soc > 100.0:
            self.soc = torch.tensor(100.0)
        elif self.soc < 0.0:
            self.soc = torch.zeros(1)

    def update_capacity(self, I: torch.Tensor | float):
        """
        Update the available charge q0 based on the current and time interval of the current timestep.
        :param I: Current at the current timestep  [unit: A]
        :param dt_hr: Time interval of the current timestep  [unit: Hr]
        """
        self.soc_prev = self.soc
        self.I_losses = 0.0
        self.cell_current = I

        # compute charge change ( I > 0 discharging, I < 0 charging)
        self.q0 -= self.cell_current[0] * self.dt_hr

        # check if SOC constraints violated, update q0, I if so
        self.check_soc()

        # update SOC, DOD
        self.update_soc()
        self.check_charge_change()

    def update_capacity_for_lifetime(self, capacity_percent: torch.Tensor | float):
        """
        Update the maximum available charge at the current timestep based on the lifetime degradation model.
        """
        if capacity_percent < 0:
            capacity_percent = 0
        if self.qmax_init * capacity_percent * 0.01 <= self.qmax_lifetime:
            self.q_max = self.qmax_init * capacity_percent * 0.01
        if self.q0 > self.qmax_lifetime:
            self.I_losses += (self.q0 - self.qmax_lifetime) / self.dt_hr
            self.q0 = self.qmax_lifetime
        self.update_soc()
