import torch
import torch.nn as nn


class NMCLifetimeModel(nn.Module):
    """
    NMC Life Model
    Based on the model developed by NREL:
    K. Smith, A. Saxon, M. Keyser, B. Lundstrom, Ziwei Cao, A. Roc
    Life prediction model for grid-connected li-ion battery energy storage system
    2017 American Control Conference (ACC) (2017), pp. 4062-4068
    https://ieeexplore.ieee.org/document/7963578
    """
    Rug = 8.314  # [J/mol-K] - Universal gas constant
    F = 96485  # [C/mol] - Faraday's constant
    T_ref = 298.15  # [K] - Reference temperature

    def __init__(
        self,
        dt_hr: torch.Tensor | float
    ):
        super().__init__()
        self.q_relative = torch.tensor(0.0)  # total lifetime relative capacity %
        self.n_cycles = torch.tensor(0.0)  # number of cycles
        self.range = torch.tensor(0.0)  # %, range of the battery
        self.average_range = torch.tensor(0.0)  # %, average range of the battery
        self.day_age_of_battery = torch.tensor(0.0)  # days, age of the battery
        # NMC lifetime model states
        self.q_relative_li = torch.tensor(0.0)  # %, SEI degradation
        self.q_relative_neg = torch.tensor(0.0)  # %, cycle degradation
        self.dq_relative_li_old = torch.tensor(0.0)  # %, SEI degradation at previous timestep
        self.dq_relative_neg_old = torch.tensor(0.0)  # %, cycle degradation at previous timestep
        self.dod_max = torch.tensor(0.0)  # %, maximum depth of discharge
        self.n_cycles_prev_day = torch.tensor(0.0)  # number of cycles in the previous day

        # parameters for reference anode and cell potential
        self.Uneg_ref = torch.tensor(0.08)
        self.V_ref = torch.tensor(3.7)
        # parameters for capacity degradation due to positive electrode-site-limit
        self.d0_ref = torch.tensor(75.1)
        self.Ea_d0_1 = torch.tensor(4126.0)
        self.Ea_d0_2 = torch.tensor(9752000.0)
        self.Ah_ref = torch.tensor(75.)
        # parameters for capacity degradation due to SEI
        self.b0 = torch.tensor(1.07)
        self.b1_ref = torch.tensor(0.003503)
        self.Ea_b1 = torch.tensor(35392.)
        self.alpha_a_b1 = torch.tensor(-1.)
        self.beta_b1 = torch.tensor(2.157)
        self.gamma = torch.tensor(2.472)
        self.b2_ref = torch.tensor(0.00001541)
        self.Ea_b_2 = torch.tensor(-42800.)
        self.b3_ref = torch.tensor(0.02805)
        self.Ea_b3 = torch.tensor(42800.)
        self.alpha_a_b3 = torch.tensor(0.0066)
        self.tau_b3 = torch.tensor(5.)
        self.theta = torch.tensor(0.135)
        # parameters for capacity degradation due to cycles
        self.c0_ref = torch.tensor(75.64)
        self.Ea_c0_ref = torch.tensor(2224.)
        self.c2_ref = torch.tensor(0.0039193)
        self.Ea_c2 = torch.tensor(-48260.)
        self.s = torch.tensor(0.0)
        self.beta_c2 = torch.tensor(4.54)
        self.cum_dt = torch.tensor(0.0)
        self.b1_dt = torch.tensor(0.0)
        self.b2_dt = torch.tensor(0.0)
        self.b3_dt = torch.tensor(0.0)
        self.c0_dt = torch.tensor(0.0)
        self.c2_dt = torch.tensor(0.0)
        # timestep
        self.dt_hr = dt_hr

    @staticmethod
    def calculate_Uneg(soc: torch.Tensor | float):
        """
        Calculate negative electrode voltage as a function of SOC with piecewise linear interpolation
        """
        if soc <= 0.1:
            return ((0.2420 - 1.2868) / 0.1) * soc + 1.2868
        else:
            return ((0.0859 - 0.2420) / 0.9) * (soc - 0.1) + 0.2420

    @staticmethod
    def calculate_Voc(soc: torch.Tensor | float):
        """
        Calculate open circuit voltage as a function of SOC with piecewise linear interpolation
        """
        if soc <= 0.1:
            return (0.4679 / 0.1) * soc + 3
        elif soc <= 0.6:
            return ((3.747 - 3.4679) / 0.5) * (soc - 0.1) + 3.4679
        else:
            return ((4.1934 - 3.7469) / 0.4) * (soc - 0.6) + 3.7469

    def runQli(self, T_battery: torch.Tensor | float):
        """
        Calculate the SEI degradation
        """
        dt_day = 1
        dn_cycles = self.n_cycles - self.n_cycles_prev_day
        b1 = self.b1_dt
        b2 = self.b2_dt
        b3 = self.b3_dt

        self.b1_dt = 0
        self.b2_dt = 0
        self.b3_dt = 0

        # Reversible thermal capacity dependence
        d0_t = (
            self.d0_ref *
            torch.exp(
                -(self.Ea_d0_1 / self.Rug) * (1 / T_battery - 1 / self.T_ref) -
                (self.Ea_d0_2 / self.Rug) * torch.pow(1 / T_battery - 1 / self.T_ref, 2)
            )
        )

        if self.day_age_of_battery > 0:
            k_cal =\
            (
                (0.5*b1) / torch.sqrt(self.day_age_of_battery) +
                (b3 / self.tau_b3) * torch.exp(-(self.day_age_of_battery / self.tau_b3))
            )

        dq_new = k_cal * dt_day + b2 * dn_cycles + self.dq_relative_li_old
        self.dq_relative_li_old = dq_new
        self.q_relative_li = d0_t / self.Ah_ref * (self.b0 - dq_new) * 100
        return self.q_relative_li

    def runQneg(self):
        """
        Calculate the cycle degradation
        """
        dn_cycles = self.n_cycles - self.n_cycles_prev_day
        c0 = self.c0_dt
        c2 = self.c2_dt
        self.c0_dt = 0
        self.c2_dt = 0

        if self.n_cycles > 0:
            dq_new = c2 / torch.sqrt(c0 * c0 - 2 * c2 * c0 * self.n_cycles) * dn_cycles + self.dq_relative_neg_old

        self.dq_relative_neg_old = dq_new
        self.q_relative_neg = c0 / self.Ah_ref * (1 - dq_new) * 100

        return self.q_relative_neg

    def integrateDegLoss(self, dod: torch.Tensor | float, T_battery: torch.Tensor | float):
        self.q_relative_li = self.runQli(T_battery)
        self.q_relative_neg = self.runQneg()
        self.q_relative = torch.minimum(self.q_relative_li, self.q_relative_neg)

        # reset DOD_max for cycle tracking
        self.cum_dt = 0
        if self.n_cycles - self.n_cycles_prev_day > 0:
            self.dod_max = dod
        self.n_cycles_prev_day = self.n_cycles

    def integrateDegParams(
        self, dt_day: torch.Tensor | float, dod: torch.Tensor | float, T_battery: torch.Tensor | float
    ):
        SOC = 0.01 * (100 - dod)
        dod_max = self.dod_max * 0.01
        # compute open circuit and negative electrode voltage as function of SOC
        U_neg = self.calculate_Uneg(SOC)
        V_oc = self.calculate_Voc(SOC)

        # multiply by timestep in days and populate corresponding vectors
        b1_dt_el = (
            self.b1_ref * torch.exp(-(self.Ea_b1 / self.Rug) * (1. / T_battery - 1. / self.T_ref)) *
            torch.exp((self.alpha_a_b1 * self.F / self.Rug) * (U_neg / T_battery - self.Uneg_ref / self.T_ref)) *
            torch.exp(self.gamma * torch.pow(dod_max, self.beta_b1)) * dt_day
        )
        b2_dt_el = self.b2_ref * torch.exp(-(self.Ea_b_2 / self.Rug) * (1. / T_battery - 1. / self.T_ref)) * dt_day
        b3_dt_el = (
            self.b3_ref * torch.exp(-(self.Ea_b3 / self.Rug) * (1. / T_battery - 1. / self.T_ref)) *
            torch.exp((self.alpha_a_b3 * self.F / self.Rug) * (V_oc / T_battery - self.V_ref / self.T_ref)) *
            (1 + self.theta * dod_max) * dt_day
        )

        # update the degradation parameters
        self.b1_dt += b1_dt_el
        self.b2_dt += b2_dt_el
        self.b3_dt += b3_dt_el

        # computations for q_neg
        c2_dt_el = (
            self.c2_ref * torch.exp(-(self.Ea_c2 / self.Rug) * (1. / T_battery - 1. / self.T_ref)) *
            torch.pow(0.01 * self.dod_max, self.beta_c2) * dt_day
        )
        c0_dt_el = self.c0_ref * torch.exp(-self.Ea_c0_ref / self.Rug * (1 / T_battery - 1 / self.T_ref)) * dt_day
        self.c0_dt += c0_dt_el
        self.c2_dt += c2_dt_el
        self.cum_dt += dt_day

    def rainflow(self, dod: torch.Tensor | float):
        """
        Rainflow counting algorithm at the current depth-of-discharge (DOD) to determine cycle
        """
        pass

    def run(
        self,
        charge_changed: bool,
        prev_dod: torch.Tensor | float,
        dod: torch.Tensor | float,
        T_battery: torch.Tensor | float
    ):
        """
        Run the NMC lifetime model to calculate the relative capacity of the battery
        """
        q_last = self.q_relative
        # convert battery temperature to Kelvin
        T_battery += 273.15
        if charge_changed:
            self.rainflow(prev_dod)
        dt_day = 1/24. * self.dt_hr
        new_cum_dt = self.cum_dt + dt_day

        if new_cum_dt > 1 + 1e-7:
            dt_day_to_end_of_day = 1 - self.cum_dt
            DOD_at_end_of_day = (dod - prev_dod) / dt_day * dt_day_to_end_of_day + prev_dod
            self.dod_max = torch.maximum(DOD_at_end_of_day, self.dod_max)
            self.day_age_of_battery += dt_day_to_end_of_day
            self.integrateDegParams(dt_day_to_end_of_day, DOD_at_end_of_day, T_battery)
            self.integrateDegLoss(DOD_at_end_of_day, T_battery)
            dt_day = new_cum_dt - 1

        self.dod_max = torch.maximum(dod, self.dod_max)
        self.day_age_of_battery += dt_day
        self.integrateDegParams(dt_day, dod, T_battery)

        if torch.abs(self.cum_dt - 1) < 1e-7:
            self.integrateDegLoss(dod, T_battery)
        self.q_relative = torch.minimum(self.q_relative, q_last)
