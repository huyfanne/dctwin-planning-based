from typing import Tuple

import torch
import torch.nn as nn
from loguru import logger

from dclib.cooling.plant.facilities.tank import Tank
from tqdm import tqdm

from dctwin.data import Batch, Buffer
from dctwin.utils.const import rho_water, water_specific_heat


class ThermalStorageTankModel(nn.Module):
    """
    Implement the learnable Thermal Storage Tank model.
    """

    def __init__(
        self,
        config: Tank,
        key_mapping: dict,
        learnable: bool = True,
    ) -> None:
        super(ThermalStorageTankModel, self).__init__()
        self.uid = config.uid
        self.volume = config.cooling.tank_volume
        self.tank_mass = rho_water * self.volume  # kg
        self.epsilon_source = nn.Parameter(
            torch.tensor(config.cooling.source_side_heat_transfer_effectiveness, dtype=torch.float32),
            requires_grad=learnable
        )
        self.epsilon_use = nn.Parameter(
            torch.tensor(config.cooling.use_side_heat_transfer_effectiveness, dtype=torch.float32),
            requires_grad=learnable
        )
        self.tank_UA = nn.Parameter(
            torch.tensor(config.cooling.heat_gain_coefficient_from_ambient_temperature, dtype=torch.float32),
            requires_grad=learnable
        )
        self.opt = torch.optim.Adam(self.parameters(), lr=1e-1)
        self.min_loss = 1e-3

        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping

    def collect(self, data: dict) -> None:
        self.buffer.add(
            Batch(
                T_tank_current=data[self.key_mapping["tank water temperature"]],
                T_tank_next=data[self.key_mapping["tank water temperature next"]],
                T_outdoor=data[self.key_mapping["outlet air temperature"]],
                T_use_in=data[self.key_mapping["use side water inlet temperature"]],
                T_source_in=data[self.key_mapping["source side water inlet temperature"]],
                m_use=data[self.key_mapping["use side water mass flow rate"]],
                m_source=data[self.key_mapping["source side water mass flow rate"]],
            )
        )

    def learn(self) -> None:
        batch, _ = self.buffer.sample(batch_size=0)
        mask = batch.supply_air_mass_flow_rate > 0
        batch = batch[mask]
        if len(batch) > 3:
            self.train()
            logger.info(f"Start learning the heat exchanger model @ {self.uid}.")
            pbar = tqdm(range(self.max_learning_iter))
            for _ in pbar:
                self.opt.zero_grad()
                T_tank_next = self(
                    T_tank_current=batch.T_tank_current,
                    T_outdoor=batch.T_outdoor,
                    T_use_in=batch.T_use_in,
                    T_source_in=batch.T_source_in,
                    m_use=batch.m_use,
                    m_source=batch.m_source,
                    time=batch.time
                )
                loss = torch.mean((T_tank_next - batch.T_tank_next) ** 2)
                loss.backward()
                self.opt.step()
                pbar.set_description(f"Loss: {loss.item():.4f}")
                if loss.item() < self.min_loss:
                    break
        else:
            logger.warning(f"Insufficient data for learning the tank model {self.uid}.")

    def forward(
        self,
        T_tank_current: torch.Tensor,
        T_outdoor: torch.Tensor,
        T_use_in: torch.Tensor,
        T_source_in: torch.Tensor,
        m_use: torch.Tensor,
        m_source: torch.Tensor,
        time: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Simulate the cooling tank temperature with the given use and source side mass flow rates and temperatures.
        Governing ODE:
        dT_tank/dt = a + b * T_tank
        T_tank = ((a / b) + (T_tank0)) * exp(b * time) - (a / b)
        a = (UA * T_outdoor / c_p + epsilon_use * m_use * T_use_in + epsilon_source * m_source * T_source_in) / tank_mass
        b = -(UA / c_p + epsilon_use * m_use + epsilon_source * m_source) / tank_mass

        Please refer to
        https://bigladdersoftware.com/epx/docs/9-5/engineering-reference/water-thermal-tanks-includes-water-heaters.html#energy-balance
        :param T_tank_current: the current tank temperature
        :param T_outdoor: the outdoor temperature
        :param T_use_in: the use side water inlet temperature
        :param T_source_in: the source side water inlet temperature
        :param m_use: the use side water mass flow rate
        :param m_source: the source side water mass flow rate
        :param time: the time step in seconds
        :return: the tank temperature at the next time step
        """
        a = self.tank_UA * T_outdoor / water_specific_heat + \
            self.epsilon_use * m_use * T_use_in + \
            self.epsilon_source * m_source * T_source_in
        a = a / self.tank_mass
        b = - (self.tank_UA / water_specific_heat + self.epsilon_use * m_use + self.epsilon_source * m_source)
        b = b / self.tank_mass
        T_tank_next = ((a / b) + T_tank_current) * torch.exp(b * time) - (a / b)
        source_side_cooling_load = m_source * (T_tank_current - T_source_in) * water_specific_heat
        use_side_cooling_load = m_use * (T_use_in - T_tank_current) * water_specific_heat

        return T_tank_next, source_side_cooling_load, use_side_cooling_load
