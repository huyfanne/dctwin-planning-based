# class CoolingCoilModel(nn.Module):
#     """
#     Implement the learnable cooling coil model. The model can take the supply air setpoint, chilled water setpoint,
#     supply air flow rate and coil inlet air temperature as input and output the chilled water mass flow rate. The
#     cooling coil model is a counter flow heat exchanger model. The coil U-factor model is a parametrized model.
#     """
#     def __init__(
#         self, config: ACU, key_mapping: dict, learnable: bool = True
#     ):
#         super(CoolingCoilModel, self).__init__()
#         self.config = config
#         self.uid = config.uid
#         self.device = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")
#         self.A = nn.Parameter(
#             torch.distributions.uniform.Uniform(low=5000, high=100000).sample((1, 1)).to(self.device),
#             requires_grad=learnable
#         )
#         self.B = nn.Parameter(
#             torch.distributions.uniform.Uniform(low=5000, high=100000).sample((1, 1)).to(self.device),
#             requires_grad=learnable
#         )
#         self.C = nn.Parameter(
#             torch.distributions.uniform.Uniform(low=5000, high=100000).sample((1, 1)).to(self.device),
#             requires_grad=learnable
#         )
#         self.learnable = learnable
#         self.max_iter = 80000
#         self.opt = torch.optim.Adam(self.parameters(), lr=1.)
#         # define the replay buffer
#         self.buffer = Buffer(size=100)
#         self.key_mapping = key_mapping
#
#     def _eta_counter_flow(
#         self,
#         water_mass_flow_rate: torch.Tensor,
#         air_mass_flow_rate: torch.Tensor
#     ):
#         """
#         Calculate the effectiveness of counter flow heat exchanger. The calculation is based on the EnergyPlus document.
#         In this equation, we use NTU-Effectiveness method to evaluate the thermal performance of a heat exchanger.
#         The coil U-factor is modelled as a function of the air-side and water-side convective heat transfer coefficient.
#         The convective heat transfer coefficient is modelled as a function of the air mass flow rate and water mass flow
#         rate. 0.8 is the correction factor for the convective heat transfer coefficient.
#
#         :param water_mass_flow_rate: the water mass flow rate (kg/s)
#         :param air_mass_flow_rate: the air mass flow rate (kg/s)
#         :return: the effectiveness of the counter flow heat exchanger (dimensionless)
#         """
#         coil_ua = 1 / (1/(self.A * (air_mass_flow_rate**0.8)) + 1/(self.B * (water_mass_flow_rate**0.8)) + 1/self.C)
#         min_stream_capacity = water_mass_flow_rate * cp_water
#         max_stream_capacity = air_mass_flow_rate * cp_air
#         # calculate the NTU number and the stream capacity ratio
#         ntu = coil_ua / min_stream_capacity
#         r = min_stream_capacity / max_stream_capacity
#         # calculate the effectiveness of counter flow heat exchanger
#         denorm = 1 - torch.exp(-ntu * (1 - r))
#         norm = 1 - r * torch.exp(-ntu * (1 - r))
#         res = denorm / (norm + 1e-9)  # add a small number to avoid numerical issue
#         # calculate the residual
#         return res.view(-1, 1)
#
#     def _loss(
#         self,
#         air_mass_flow_rate: torch.Tensor,
#         water_mass_flow_rate: torch.Tensor,
#         inlet_air_temperature: torch.Tensor,
#         chilled_water_supply_temperature: torch.Tensor,
#         outlet_air_temperature: torch.Tensor
#     ):
#         """
#         Implement the physical loss function of the cooling coil. The loss function is the mean squared error between
#         the estimated supply air temperature and the supply air setpoint. By using this loss function, we can learn the
#         parameters in the cooling coil U-factor model that satisfies the air-side energy and heat balance.
#         :param air_mass_flow_rate: the air mass flow rate (kg/s)
#         :param water_mass_flow_rate: the water mass flow rate (kg/s)
#         :param inlet_air_temperature: the inlet air temperature of the cooling coil (C)
#         :param chilled_water_supply_temperature: the chilled water supply temperature (C)
#         :param outlet_air_temperature: the outlet air temperature of the cooling coil (C)
#         :return:
#         """
#         eta = self._eta_counter_flow(
#             water_mass_flow_rate=water_mass_flow_rate,
#             air_mass_flow_rate=air_mass_flow_rate,
#         )
#         estimated_outlet_air_temperature = (
#             inlet_air_temperature - eta * cp_water * water_mass_flow_rate
#             * (inlet_air_temperature - chilled_water_supply_temperature) / (cp_air * air_mass_flow_rate)
#         )
#         return nn.MSELoss()(estimated_outlet_air_temperature, outlet_air_temperature)
#
#     def _project_ws(self):
#         """Make sure the A and B are positive according to their physical meaning."""
#         self.A.data = torch.clamp(self.A.data, 0, torch.inf)
#         self.B.data = torch.clamp(self.B.data, 0, torch.inf)
#         self.C.data = torch.clamp(self.C.data, 0, torch.inf)
#
#     def _bisection(
#         self,
#         water_mass_flow_rate_min,
#         water_mass_flow_rate_max,
#         air_mass_flow_rate,
#         inlet_air_temperature: torch.Tensor,
#         chilled_water_supply_temperature: torch.Tensor,
#         outlet_air_temperature: torch.Tensor,
#         tol=1e-6,
#         max_iter=500
#     ):
#         m_w_star = (water_mass_flow_rate_min + water_mass_flow_rate_max) / 2
#         # evaluate the air outlet temperature based on the current water mass flow rate
#         eta = self._eta_counter_flow(
#             water_mass_flow_rate=m_w_star,
#             air_mass_flow_rate=air_mass_flow_rate,
#         )
#         estimated_outlet_air_temperature = (
#             inlet_air_temperature - eta * cp_water * m_w_star *
#             (inlet_air_temperature - chilled_water_supply_temperature) / (cp_air * air_mass_flow_rate)
#         )
#         residual = estimated_outlet_air_temperature - outlet_air_temperature
#         iteration = 1
#         # bi-section main loop
#         while torch.abs(residual) > tol and iteration < max_iter:
#             if residual > 0:
#                 water_mass_flow_rate_min = m_w_star
#             else:
#                 water_mass_flow_rate_max = m_w_star
#             m_w_star = (water_mass_flow_rate_min + water_mass_flow_rate_max) / 2
#             eta = self._eta_counter_flow(
#                 water_mass_flow_rate=m_w_star,
#                 air_mass_flow_rate=air_mass_flow_rate,
#             )
#             estimated_outlet_air_temperature = (
#                 inlet_air_temperature - eta * cp_water * m_w_star
#                 * (inlet_air_temperature - chilled_water_supply_temperature) / (cp_air * air_mass_flow_rate)
#             )
#             residual = estimated_outlet_air_temperature - outlet_air_temperature
#             iteration += 1
#         return m_w_star
#
#     def forward(
#         self,
#         supply_air_sp: torch.Tensor,
#         supply_air_flow_rate: torch.Tensor,
#         inlet_air_temperature: torch.Tensor,
#         chw_sp: torch.Tensor
#     ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
#         """
#         Calculate the chilled water mass flow rate based on the supply air setpoint, chilled water setpoint, supply
#         air flow rate and coil inlet air temperature. The chilled water mass flow rate m_{w}^{*} is calculated by
#         finding the root of the following air-side energy and heat balance equation:
#
#             m_{w}^{*} = f(m_a, m_w) = 0 <-> T_sp=T_{out}^{air}=T_{in}^{air}-\frac{eta(m_a, m_w)*Q_{max}(m_w)}{(Cp_a*m_a}
#
#         where Q_{max}(m_w) = Cp_w * m_w * (T_z - T_w) is the maximum heat transfer rate of the coil, Cp_w is the
#         specific heat of water, T_w is the chilled water temperature, T_z is the zone temperature (which is also the
#         inlet air temperature of the cooling coil).
#
#         :param supply_air_sp: the supply air setpoint temperature (C)
#         :param supply_air_flow_rate: the supply air flow rate (kg/s)
#         :param inlet_air_temperature: the inlet air temperature of the cooling coil (C)
#         :param chw_sp: the chilled water setpoint temperature (C)
#         :return: the chilled water mass flow rate that satisfies the air-side energy and heat balance (kg/s)
#         """
#         # calculate the minimum and maximum chilled water mass flow rate
#         # with torch.no_grad():
#         #     m_w_min = 1e-6 * torch.ones_like(supply_air_flow_rate)
#         #     m_w_max = cp_air * supply_air_flow_rate / cp_water
#         #     m_w_star = self._bisection(
#         #         water_mass_flow_rate_min=m_w_min,
#         #         water_mass_flow_rate_max=m_w_max,
#         #         air_mass_flow_rate=supply_air_flow_rate,
#         #         inlet_air_temperature=inlet_air_temperature,
#         #         outlet_air_temperature=supply_air_sp,
#         #         chilled_water_supply_temperature=chw_sp,
#         #     )
#         # calculate the effective heat transfer rate
#         # eta = self._eta_counter_flow(
#         #     water_mass_flow_rate=m_w_star,
#         #     air_mass_flow_rate=supply_air_flow_rate,
#         # )
#         # calculate the required chilled water mass flow rate
#         m_w_star = cp_air * supply_air_flow_rate / cp_water
#         coil_cooling_rate = cp_air * supply_air_flow_rate * (inlet_air_temperature - supply_air_sp)
#         outlet_air_temperature = inlet_air_temperature - coil_cooling_rate / (cp_air * supply_air_flow_rate)
#         return m_w_star, coil_cooling_rate, outlet_air_temperature
#
#     def collect(self, data: dict):
#         assert "inlet air temperature" in self.key_mapping.keys(), \
#             "The \"inlet air temperature\" key is not provided."
#         assert "outlet air temperature" in self.key_mapping.keys(), \
#             "The \"outlet air temperature\" key is not provided."
#         assert "air mass flow rate" in self.key_mapping.keys(), \
#             "The \"air mass flow rate\" key is not provided."
#         assert "water mass flow rate" in self.key_mapping.keys(), \
#             "The \"water mass flow rate\" key is not provided."
#         assert "inlet water temperature" in self.key_mapping.keys(), \
#             "The \"inlet water temperature\" key is not provided."
#         assert self.key_mapping["inlet air temperature"] in data.keys(), \
#             f"{self.key_mapping['inlet air temperature']} is not included in the data dictionary."
#         assert self.key_mapping["outlet air temperature"] in data.keys(), \
#             f"{self.key_mapping['outlet air temperature']} is not included in the data dictionary."
#         assert self.key_mapping["air mass flow rate"] in data.keys(), \
#             f"{self.key_mapping['air mass flow rate']} is not included in the data dictionary."
#         assert self.key_mapping["water mass flow rate"] in data.keys(), \
#             f"{self.key_mapping['water mass flow rate']} is not included in the data dictionary."
#         self.buffer.add(
#             Batch(
#                 cooling_coil_inlet_air_temperature=data[self.key_mapping["inlet air temperature"]],
#                 cooling_coil_outlet_air_temperature=data[self.key_mapping["outlet air temperature"]],
#                 cooling_coil_air_mass_flow_rate=data[self.key_mapping["air mass flow rate"]],
#                 cooling_coil_water_mass_flow_rate=data[self.key_mapping["water mass flow rate"]],
#                 cooling_coil_inlet_water_temperature=data[self.key_mapping["inlet water temperature"]],
#             )
#         )
#
#     def learn(self):
#         if self.learnable:
#             pbar = tqdm(range(self.max_iter))
#             batch, _ = self.buffer.sample(batch_size=0)  # sample a batch of data from the replay buffer
#             for _ in pbar:
#                 self.train()
#                 self.opt.zero_grad()
#                 loss = self._loss(
#                     inlet_air_temperature=torch.tensor(
#                         batch.cooling_coil_inlet_air_temperature, dtype=torch.float32
#                     ).view(-1, 1),
#                     outlet_air_temperature=torch.tensor(
#                         batch.cooling_coil_outlet_air_temperature, dtype=torch.float32
#                     ).view(-1, 1),
#                     air_mass_flow_rate=torch.tensor(
#                         batch.cooling_coil_air_mass_flow_rate, dtype=torch.float32
#                     ).view(-1, 1),
#                     water_mass_flow_rate=torch.tensor(
#                         batch.cooling_coil_water_mass_flow_rate, dtype=torch.float32
#                     ).view(-1, 1),
#                     chilled_water_supply_temperature=torch.tensor(
#                         batch.cooling_coil_inlet_water_temperature, dtype=torch.float32
#                     ).view(-1, 1),
#                 )
#                 loss.backward()
#                 self.opt.step()
#                 self._project_ws()  # project the parameters to the positive region to make them feasible
#                 pbar.set_description(f"Loss: {loss.item():.4f}")
#         else:
#             pass


from CoolProp.CoolProp import PropsSI
import numpy as np
import torch
import torch.nn as nn
from dclib.cooling.room.facilities import ACU

from dcdyn.data import Batch, Buffer

from tqdm import tqdm

from .utils.parameter_calc import NTUHE, nusseltCoefficient, nusseltNumberIn


class CoolingCoilModel(nn.Module):

    def __init__(
        self,
        config: ACU,
        key_mapping: dict,
        learnable: bool = True,
        internal_fluid_name: str = "water",
        extern_fluid_name: str = "air",
        tube_diameter: float = 0.02,
        tube_length: float = 2.5,
        tube_thickness: float = 0.002,
        tube_roughness: float = 1e-5,
        row_number: float | int = 80,
        row_pitch: float = 0.03,
        transverse_number: float | int = 60,
        transverse_pitch: float | int = 0.03,
        thermal_conductivity: float = 400,
        tol: float = 0.01,
        max_root_finding_iter: int = 50,
        max_learning_iter: int = 50,
    ):
        """
        A PIML-based model for cooling coil inside an ACU. It leverages the geometry information of the cooling coil as
        well as the physical property of the internal and external fluids to calculate the outlet temperatures of the
        cooling coil. The model is based on the NTU-effectiveness heat exchanger model.
        :param key_mapping:
        :param internal_fluid_name:
        :param extern_fluid_name:
        :param tube_diameter:
        :param tube_length:
        :param tube_thickness:
        :param tube_roughness:
        :param row_number:
        :param row_pitch:
        :param transverse_number:
        :param transverse_pitch:
        :param thermal_conductivity:
        """
        super().__init__()
        self.config = config
        self.uid = config.uid
        self.device = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")

        self.tube_diameter = nn.Parameter(
            torch.tensor(tube_diameter, dtype=torch.float32),
            requires_grad=False
        )
        self.tube_length = nn.Parameter(
            torch.tensor(tube_length, dtype=torch.float32),
            requires_grad=True
        )
        self.tube_thickness = nn.Parameter(
            torch.tensor(tube_thickness, dtype=torch.float32),
            requires_grad=False
        )
        self.num_row = nn.Parameter(
            torch.tensor(row_number, dtype=torch.float32),
            requires_grad=True
        )
        self.num_transverse = nn.Parameter(
            torch.tensor(transverse_number, dtype=torch.float32),
            requires_grad=True
        )
        self.row_pitch = nn.Parameter(
            torch.tensor(row_pitch, dtype=torch.float32),
            requires_grad=False
        )
        self.transverse_pitch = nn.Parameter(
            torch.tensor(transverse_pitch, dtype=torch.float32),
            requires_grad=False
        )
        self.tube_roughness = nn.Parameter(
            torch.tensor(tube_roughness, dtype=torch.float32),
            requires_grad=False
        )
        self.tube_kappa = nn.Parameter(
            torch.tensor(thermal_conductivity, dtype=torch.float32), requires_grad=False
        )
        self.H_he = self.num_transverse * self.transverse_pitch + 2 * self.tube_diameter
        self.standard_atomos_pressure = 101325

        self.internal_fluid_name = internal_fluid_name
        self.extern_fluid_name = extern_fluid_name

        self.key_mapping = key_mapping
        self.buffer = Buffer(size=100)
        self.opt = torch.optim.Adam(self.parameters(), lr=0.1)
        self.learnable = learnable
        self.max_learning_iter = max_learning_iter
        self.tol = tol
        self.max_root_finding_iter = max_root_finding_iter

    def _correct_nusselt_number(self, nu: torch.Tensor):
        if self.num_row < 20:
            N_list = np.array([1, 2, 3, 4, 5, 7, 10, 13, 16])  # row number list
            N_list = abs(N_list - np.array(self.num_row))  # difference between row number and row number list
            coef2_list = [0.7, 0.8, 0.86, 0.9, 0.92, 0.95, 0.97, 0.98, 0.99]  # correction coefficient list
            min_id = np.where(N_list == np.min(N_list))[0]  # minimum difference id
            coef2 = coef2_list[min_id[0]]  # correction coefficient
            nu *= coef2  # corrected external fluid Nusselt number
        return nu

    def _cal_physical_property(
        self,
        T_water_in: torch.Tensor,
        T_air_in: torch.Tensor
    ):
        rho_i = torch.zeros(T_water_in.shape)
        Cp_i = torch.zeros(T_water_in.shape)
        k_i = torch.zeros(T_water_in.shape)
        miu_i = torch.zeros(T_water_in.shape)
        Pr_i = torch.zeros(T_water_in.shape)
        rho_o = torch.zeros(T_air_in.shape)
        Cp_o = torch.zeros(T_air_in.shape)
        k_o = torch.zeros(T_air_in.shape)
        miu_o = torch.zeros(T_air_in.shape)
        Pr_o = torch.zeros(T_air_in.shape)
        for idx, val in enumerate(T_water_in):
            rho_i[idx] = PropsSI(
                'D', 'P', self.standard_atomos_pressure, 'T',
                val.item() + 273.15, self.internal_fluid_name
            )
            rho_o[idx] = PropsSI(
                'D', 'P', self.standard_atomos_pressure, 'T',
                val.item() + 273.15, self.extern_fluid_name
            )
            Cp_i[idx] = PropsSI(
                'C', 'P', self.standard_atomos_pressure, 'T',
                val.item() + 273.15, self.internal_fluid_name
            )
            Cp_o[idx] = PropsSI(
                'C', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.extern_fluid_name
            )
            k_i[idx] = PropsSI(
                'CONDUCTIVITY', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.internal_fluid_name
            )
            k_o[idx] = PropsSI(
                'CONDUCTIVITY', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.extern_fluid_name
            )
            miu_i[idx] = PropsSI(
                'V', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.internal_fluid_name
            )
            miu_o[idx] = PropsSI(
                'V', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.extern_fluid_name
            )
            Pr_i[idx] = PropsSI(
                'PRANDTL', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.internal_fluid_name
            )
            Pr_o[idx] = PropsSI(
                'PRANDTL', 'P', self.standard_atomos_pressure,
                'T', val.item() + 273.15, self.extern_fluid_name
            )
        return rho_i, Cp_i, k_i, miu_i, Pr_i, rho_o, Cp_o, k_o, miu_o, Pr_o

    def _project_ws(self):
        """Make sure the A and B are positive as they are physical quantities."""
        self.num_row.data = torch.clamp(self.num_row.data, 0, torch.inf)
        self.num_transverse.data = torch.clamp(self.num_transverse.data, 0, torch.inf)
        self.tube_length.data = torch.clamp(self.tube_length.data, 0, torch.inf)

    def collect(self, data: dict):
        self.buffer.add(
            Batch(
                cooling_coil_inlet_air_temperature=data[self.key_mapping["inlet air temperature"]],
                cooling_coil_outlet_air_temperature=data[self.key_mapping["outlet air temperature"]],
                cooling_coil_air_mass_flow_rate=data[self.key_mapping["air mass flow rate"]],
                cooling_coil_water_mass_flow_rate=data[self.key_mapping["water mass flow rate"]],
                cooling_coil_inlet_water_temperature=data[self.key_mapping["inlet water temperature"]],
            )
        )

    def learn(self):
        if self.learnable:
            pbar = tqdm(range(self.max_learning_iter))
            batch, _ = self.buffer.sample(batch_size=0)  # sample all data from the buffer
            self.train()
            for _ in pbar:
                self.opt.zero_grad()
                _, T_air_out, _, _, _, _ = self.forward(
                    T_air_in=torch.tensor(
                        batch.cooling_coil_inlet_air_temperature, dtype=torch.float32
                    ).view(-1, 1),
                    m_air=torch.tensor(
                        batch.cooling_coil_air_mass_flow_rate, dtype=torch.float32
                    ).view(-1, 1),
                    m_water=torch.tensor(
                        batch.cooling_coil_water_mass_flow_rate, dtype=torch.float32
                    ).view(-1, 1),
                    T_water_in=torch.tensor(
                        batch.cooling_coil_inlet_water_temperature, dtype=torch.float32
                    ).view(-1, 1),
                )
                loss = nn.MSELoss()(
                    T_air_out,
                    torch.tensor(batch.cooling_coil_outlet_air_temperature, dtype=torch.float32).view(-1, 1)
                )
                loss.backward(retain_graph=True)
                self.opt.step()
                self._project_ws()  # project the parameters to the positive region to make them feasible
                pbar.set_description(f"Loss: {loss.item():.4f}")

    def forward(
        self,
        T_air_in: torch.Tensor,
        m_air: torch.Tensor,
        T_water_in: torch.Tensor,
        m_water: torch.Tensor
    ):
        """
        Calculate the outlet temperatures of the cooling coil
        :param T_air_in: inlet air temperature
        :param m_air: air mass flow rate
        :param T_water_in: inlet water temperature
        :param m_water: water mass flow rate
        :return:
        """
        rho_i, Cp_i, k_i, miu_i, Pr_i, rho_o, Cp_o, k_o, miu_o, Pr_o = self._cal_physical_property(
            T_water_in=T_water_in,
            T_air_in=T_air_in
        )
        # tube inside
        v_water = m_water / rho_i  # internal fluid volumetric flow rate
        u_i = v_water / (self.num_row * self.num_transverse) / (torch.pi / 4 * self.tube_diameter ** 2)
        Re_i = rho_i * u_i * self.tube_diameter / miu_i  # internal fluid Reynolds number
        rr_i = self.tube_roughness / self.tube_diameter  # relative roughness
        fr, nu_i = nusseltNumberIn(rr_i, Re_i, Pr_i)  # friction factor and Nusselt number
        h_i = nu_i * k_i / self.tube_diameter  # internal fluid heat transfer coefficient

        dP_i = fr * (self.tube_length / self.tube_diameter) * (rho_i * u_i ** 2) / 2  # internal fluid pressure drop
        pump_power_i = (self.num_row * self.num_transverse) * dP_i * (m_water / rho_i)  # internal fluid pumping power

        # tube outside
        u_o = m_air / rho_o / (self.tube_length * self.H_he)  # external fluid velocity
        u_omax = self.transverse_pitch / (self.transverse_pitch - self.tube_diameter) * u_o
        Re_omax = rho_o * u_omax * self.tube_diameter / miu_o  # maximum external fluid Reynolds number
        coef1, expo1 = nusseltCoefficient(Re_omax)  # coefficient and exponent of Nusselt number
        Nu_o = coef1 * (Re_omax ** expo1) * (Pr_o ** 0.36)  # external fluid Nusselt number

        # correct the outside Nusselt number when the row number is less than 20
        Nu_o = self._correct_nusselt_number(Nu_o)
        h_o = Nu_o * k_o / self.tube_diameter  # external fluid heat transfer coefficient

        f_o = 0.2  # external fluid friction factor
        dP_o = self.num_row * (rho_o * u_omax ** 2 / 2) * f_o  # external fluid pressure drop
        pump_power_o = dP_o * (m_air / rho_o)  # external fluid pumping power

        # pumping power, U value and NTU value
        pump_power = pump_power_i + pump_power_o  # W, pumping power
        U = 1 / (
            1 / h_i + 1 / h_o + torch.log((self.tube_thickness + self.tube_diameter) / self.tube_diameter) *
            self.tube_diameter / self.tube_kappa
        )  # W/m2K, overall heat transfer coefficient
        A = self.num_transverse * self.num_row * (torch.pi * self.tube_diameter * self.tube_length)

        C_i = m_water * Cp_i  # W/K, internal fluid heat capacity
        C_o = m_air * Cp_o  # W/K, external fluid heat capacity
        C_min = torch.minimum(C_i, C_o)  # W/K, minimum heat capacity
        eff, NTU = NTUHE(C_i, C_o, U, A)  # efficiency and number transfer unit of heat exchanger
        Q_max = C_min * (T_air_in - T_water_in)  # W, maximum heat transfer
        heat_transfer_rate = eff * Q_max - pump_power  # W, heat transfer
        T_air_out = T_air_in - heat_transfer_rate / C_o  # degree C, external fluid outlet temperature
        T_water_out = T_water_in + (heat_transfer_rate + pump_power) / C_i
        return T_water_out, T_air_out, NTU, eff, heat_transfer_rate, pump_power

    def solve(
        self,
        T_air_in: torch.Tensor,
        m_air: torch.Tensor,
        T_water_in: torch.Tensor,
        T_air_out_sp: torch.Tensor,
    ):
        """
        Calculate the chilled water mass flow rate that satisfies the supply air setpoint temperature
        with Bisection method.
        :param T_air_in:
        :param m_air:
        :param T_water_in:
        :param T_air_out_sp:
        :return:
        """
        m_water_min = torch.tensor(0.0, dtype=torch.float32).view(1, -1)
        m_water_max = m_air.item()
        m_water = (m_water_min + m_water_max) / 2
        with torch.no_grad():
            T_water_out, T_air_out, NTU, eff, Q, power = self.forward(
                T_air_in=T_air_in,
                m_air=m_air,
                T_water_in=T_water_in,
                m_water=m_water
            )
            # bi-section main loop
            for iteration in range(1, self.max_root_finding_iter + 1):
                if T_air_out - T_air_out_sp > 0:
                    m_water_min = m_water
                else:
                    m_water_max = m_water
                m_water = (m_water_min + m_water_max) / 2
                T_water_out, T_air_out, NTU, eff, Q, power = self.forward(
                    T_air_in=T_air_in,
                    m_air=m_air,
                    T_water_in=T_water_in,
                    m_water=m_water
                )
                if torch.abs(T_air_out - T_air_out_sp) < self.tol:
                    break
            if iteration == self.max_root_finding_iter:
                print(f"{self.config.uid}: root finding failed at iteration {iteration}. T_air_out = {T_air_out.item()}")
        # insert gradient calculation
        with torch.enable_grad():
            m_water = m_water.requires_grad_(requires_grad=True)
            T_water_out, T_air_out, _, _, Q, _ = self.forward(
                T_air_in=T_air_in,
                m_air=m_air,
                T_water_in=T_water_in,
                m_water=m_water
            )
            g = T_air_out - T_air_out_sp
            jacob = torch.autograd.grad(
                g,
                m_water,
                retain_graph=True
            )[0]
            # reengage the gradient calculation by inserting the gradient into the computation graph
            m_water = m_water - g
        m_water.register_hook(lambda grad: grad / jacob)  # implicit gradient calculation
        return m_water, Q, T_air_out
