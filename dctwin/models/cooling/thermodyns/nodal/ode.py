import torch
from torchdiffeq import odeint

from dctwin.utils.const import air_specific_heat, rho_air


class DifferentiableODE:
    def __init__(
        self,
        t_span: torch.Tensor = torch.linspace(0, 5, 10),
        zone_volume: float = 1,
        method: str = "dopri8",
        rtol: float = 1e-6,
        atol: float = 1e-6,
    ) -> None:
        self.t_span = t_span
        self.zone_volume = zone_volume
        self.method = method
        self.rtol = rtol
        self.atol = atol

    def _make_func(
        self,
        supply_air_temperature: torch.Tensor,
        supply_air_mass_flow_rate: torch.Tensor,
        sensible_load: torch.Tensor,
    ) -> callable:
        def func(t, T_z):
            dTzdt = (1 / air_specific_heat / rho_air / self.zone_volume) * (
                sensible_load
                + supply_air_mass_flow_rate
                * air_specific_heat
                * (supply_air_temperature - T_z)
            )
            return dTzdt

        return func

    def sim(
        self,
        current_zone_temperature: torch.Tensor,
        supply_air_temperature: torch.Tensor,
        supply_air_mass_flow_rate: torch.Tensor,
        sensible_load: torch.Tensor,
    ) -> torch.Tensor:
        with torch.no_grad():
            return odeint(
                func=self._make_func(
                    supply_air_temperature, supply_air_mass_flow_rate, sensible_load
                ),
                y0=current_zone_temperature,
                t=self.t_span,
                method=self.method,
                rtol=self.rtol,
                atol=self.atol,
            ).view(-1)[-1]
