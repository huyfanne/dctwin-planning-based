import torch
import torch.nn as nn
import numpy as np
from typing import Optional, Any, Union

from dctwin.data import Batch
from dctwin.utils.const import air_specific_heat, rho_air

from .base import BaseNNDynamics


def ode(
    zone_air_temperatures: Union[float, torch.Tensor],
    supply_air_temperatures: Union[float, torch.Tensor],
    supply_air_mass_flow_rates: Union[float, torch.Tensor],
    sensible_heat_loads: Union[float, torch.Tensor],
    zone_volume: Union[float, torch.Tensor],
) -> Union[float, torch.Tensor]:
    """Based on B. Arguello-Serrano et al. IEEE TCST'99 eq.(1)
    :param zone_air_temperatures: Zone air temperature (C)
    :param supply_air_temperatures: Supply air temperature (C)
    :param supply_air_mass_flow_rates: mass air flow rate (kg/s)
    :param sensible_heat_loads: Sensible heat load (kW)
    :param zone_volume: zone volume (m^3)
    :return: dTr / dt
    """
    dTrdt = (
        supply_air_mass_flow_rates
        * (supply_air_temperatures - zone_air_temperatures)
        / (rho_air * zone_volume)
        + 1 * sensible_heat_loads / (air_specific_heat * zone_volume / 1000)
    ) * 60
    return dTrdt


class PINNDynamics(BaseNNDynamics):
    """
    Physics-informed Neural Network (PINN) dynamics model to predict
    data hall thermal transition
    :param model: neural network model
    :param model_optim: optimizer for neural network model
    :param pred_residual: whether to predict residual or not (default: True)
    """

    def __init__(
        self,
        model: Optional[nn.Module],
        model_optim: Optional[torch.optim.Optimizer],
        zone_volume: float,
        pred_residual: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            model_optim=model_optim,
            use_residual=pred_residual,
            **kwargs,
        )
        self.zone_volume = zone_volume

    def _compute_physics_loss(
        self,
        batch: Batch,
    ) -> torch.Tensor:
        time = torch.as_tensor(
            batch.times, device=self.model.device, dtype=torch.float32
        )
        time.requires_grad = True
        output = self.forward(
            batch.supply_air_temperature,
            batch.supply_air_mass_flow_rate,
            batch.zone_air_temperature,
            batch.sensible_heat_load,
            time,
        )
        phy_pred = ode(
            zone_air_temperatures=output,
            supply_air_temperatures=torch.as_tensor(batch.supply_air_temperature),
            supply_air_mass_flow_rates=torch.as_tensor(batch.supply_air_mass_flow_rate),
            sensible_heat_loads=torch.as_tensor(batch.sensible_heat_load),
            zone_volume=self.zone_volume,
        )
        physics_loss = self.df(output, time) - phy_pred
        return physics_loss.pow(2).mean()

    def _compute_initial_loss(
        self,
        batch: Batch,
    ) -> torch.Tensor:
        initial_time = torch.zeros(len(batch)).reshape(-1, 1)
        initial_time.requires_grad = True
        boundary_loss = self.forward(
            batch.supply_air_temperature,
            batch.supply_air_mass_flow_rate,
            batch.zone_air_temperature,
            batch.sensible_heat_load,
            initial_time,
        )
        return boundary_loss.pow(2).mean()

    def _compute_loss(
        self,
        batch: Batch,
        **kwargs,
    ) -> torch.Tensor:
        interior_loss = self._compute_physics_loss(batch)
        boundary_loss = self._compute_initial_loss(batch)
        return boundary_loss + interior_loss

    def forward(
        self,
        supply_air_temperatures: Union[np.ndarray, torch.Tensor],
        supply_air_mass_flow_rates: Union[np.ndarray, torch.Tensor],
        zone_air_temperatures: Union[np.ndarray, torch.Tensor],
        sensible_heat_loads: Union[np.ndarray, torch.Tensor],
        times: Union[np.ndarray, torch.Tensor],
        **kwargs,
    ) -> torch.Tensor:
        """
        Compute next (partial) observation over the given batch of
        current full observation and action.
        """
        size = supply_air_temperatures.shape[0]
        supply_air_temperatures = torch.as_tensor(
            supply_air_temperatures, dtype=torch.float32
        ).reshape(size, -1)
        supply_air_mass_flow_rates = torch.as_tensor(
            supply_air_mass_flow_rates, dtype=torch.float32
        ).reshape(size, -1)
        zone_air_temperatures = torch.as_tensor(
            zone_air_temperatures, dtype=torch.float32
        ).reshape(size, -1)
        sensible_heat_loads = torch.as_tensor(
            sensible_heat_loads, dtype=torch.float32
        ).reshape(size, -1)
        times = torch.as_tensor(times, dtype=torch.float32).reshape(size, -1)

        input_ = torch.cat(
            [
                supply_air_temperatures,
                supply_air_mass_flow_rates,
                zone_air_temperatures,
                sensible_heat_loads,
                times,
            ],
            dim=1,
        )
        output = self.model(input_)

        return self._postprocess_pred(output, zone_air_temperatures)
