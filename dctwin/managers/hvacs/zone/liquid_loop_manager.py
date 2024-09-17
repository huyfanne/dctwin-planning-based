from typing import Dict
from CoolProp.CoolProp import PropsSI
import torch
from dclib import Room
from dclib.data import Inputs

from dctwin.models.cooling.facilities.cdu import CDUModel


class LiquidLoopManager:
    """
    Implement the liquid cooling manager to simulate the thermal properties and the electrical power consumption
    of a hybrid cooling system with the direct-to-chip cooling system and conventional force ventilation air cooling
    system.
    """
    def __init__(
        self,
        room: Room,
        inputs: Inputs,
        cpu_number_per_server=8,
        fluid_name='water'
    ) -> None:
        self.room = room
        self.inputs = inputs
        self.cdus = self._make_cdus()
        self.racks = room.constructions.racks
        self.fluid_name = fluid_name
        self.cpu_number_per_server = cpu_number_per_server
        self.liquid_capacity = PropsSI('C', 'P', 101325, 'Q', 0, "water")  # J/kg/K

        # solver parameters
        self.tol = 1e-2
        self.max_iter = 50

    def _make_cdus(self) -> dict[str, CDUModel]:
        """
        Create the CDU instances according to the room configuration.
        """
        cdus = {}
        for cdu_name, cdu in self.room.constructions.cdus.items():
            # search for the racks that are under the control of the current CDU
            racks = {}
            for rack_name in cdu.meta.racks:
                racks[rack_name] = self.room.constructions.racks[rack_name]
            cdus[cdu_name] = CDUModel(
                cdu=cdu,
                racks=racks,
            )
        return cdus

    def _formatted_cdu_inputs(self, cdu_name: str):
        server_powers = {}
        server_mass_flow_rates = {}
        server_liquid_cooling_percentages = {}
        cooling_water_supply_temperature_sp = torch.tensor(self.inputs.cdus[cdu_name].cooling_water_supply_temperature_sp).view(1)
        chilled_water_supply_temperature = torch.tensor(self.inputs.cdus[cdu_name].chilled_water_supply_temperature).view(1)
        chilled_water_mass_flow_rate = None
        for rack_name in self.room.constructions.cdus[cdu_name].meta.racks:
            for server_name, server in self.room.constructions.racks[rack_name].constructions.servers.items():
                server_powers[server_name] = \
                    torch.tensor(self.inputs.servers[server_name].input_power).view(1)
                server_mass_flow_rates[server_name] = \
                    torch.tensor(self.inputs.servers[server_name].liquid_mass_flow_rate).view(1)
                server_liquid_cooling_percentages[server_name] = \
                    torch.tensor(self.inputs.servers[server_name].liquid_percentage).view(1)
        return (
            server_powers,
            server_mass_flow_rates,
            server_liquid_cooling_percentages,
            cooling_water_supply_temperature_sp,
            chilled_water_supply_temperature,
            chilled_water_mass_flow_rate,
        )

    def sim(
        self,
        server_powers: Dict[str, torch.Tensor],
        server_mass_flow_rates: Dict[str, torch.Tensor],
        server_liquid_cooling_percentages: Dict[str, torch.Tensor],
        cooling_water_supply_temperature_sps: Dict[str, torch.Tensor],
        chilled_water_supply_temperatures: Dict[str, torch.Tensor],
    ):
        cdu_electrical_powers = {}
        cdu_chilled_water_supply_temperatures = {}
        cdu_chilled_water_return_temperatures = {}
        cdu_cooling_water_supply_temperatures = {}
        cdu_cooling_water_return_temperatures = {}
        cdu_chilled_water_mass_flow_rates = {}
        cdu_cooling_water_mass_flow_rates = {}
        cdu_hx_infos = {}
        for cdu_name, cdu in self.cdus.items():
            current_server_powers = {}
            current_server_mass_flow_rates = {}
            current_server_liquid_cooling_percentages = {}
            for rack_name in self.room.constructions.cdus[cdu_name].meta.racks:
                for server_name, server in self.room.constructions.racks[rack_name].constructions.servers.items():
                    current_server_powers[server_name] = \
                        server_powers[server_name]
                    current_server_mass_flow_rates[server_name] = \
                        server_mass_flow_rates[server_name] * 1000
                    current_server_liquid_cooling_percentages[server_name] = \
                        server_liquid_cooling_percentages[server_name]
            # simulate the CDU
            cooling_water_supply_temperature = cooling_water_supply_temperature_sps[cdu_name]
            chilled_water_supply_temperature = chilled_water_supply_temperatures[cdu_name]
            (
                cdu_electrical_power,
                chilled_water_return_temperature,
                cooling_water_supply_temperature,
                cdu_return_temperature,
                chilled_water_mass_flow_rate,
                cooling_water_mass_flow_rate,
                hx_info
            ) = cdu.sim(
                server_powers=current_server_powers,
                server_mass_flow_rates=current_server_mass_flow_rates,
                server_liquid_cooling_percentages=current_server_liquid_cooling_percentages,
                cooling_water_supply_temperature=cooling_water_supply_temperature,
                chilled_water_supply_temperature=chilled_water_supply_temperature,
            )
            # update cdu simulation results
            cdu_electrical_powers[cdu_name] = cdu_electrical_power
            cdu_chilled_water_supply_temperatures[cdu_name] = chilled_water_supply_temperature
            cdu_chilled_water_return_temperatures[cdu_name] = chilled_water_return_temperature
            cdu_cooling_water_supply_temperatures[cdu_name] = cooling_water_supply_temperature
            cdu_cooling_water_return_temperatures[cdu_name] = cdu_return_temperature
            cdu_chilled_water_mass_flow_rates[cdu_name] = chilled_water_mass_flow_rate
            cdu_cooling_water_mass_flow_rates[cdu_name] = cooling_water_mass_flow_rate
            cdu_hx_infos[cdu_name] = hx_info

        return (
            cdu_electrical_powers,
            cdu_chilled_water_supply_temperatures,
            cdu_chilled_water_return_temperatures,
            cdu_cooling_water_supply_temperatures,
            cdu_cooling_water_return_temperatures,
            cdu_chilled_water_mass_flow_rates,
            cdu_cooling_water_mass_flow_rates,
            cdu_hx_infos
        )

    def run(self):
        server_powers = {}
        server_mass_flow_rates = {}
        server_liquid_cooling_percentages = {}
        cdu_cooling_water_supply_temperature_sps = {}
        cdu_chilled_water_supply_temperatures = {}

        for cdu_name in self.room.constructions.cdus:
            (
                current_server_powers,
                current_server_mass_flow_rates,
                current_server_liquid_cooling_percentages,
                cooling_water_supply_temperature_sp,
                chilled_water_supply_temperature,
                chilled_water_mass_flow_rate,
            ) = self._formatted_cdu_inputs(cdu_name)
            server_powers.update(current_server_powers)
            server_mass_flow_rates.update(current_server_mass_flow_rates)
            server_liquid_cooling_percentages.update(current_server_liquid_cooling_percentages)
            cdu_cooling_water_supply_temperature_sps[cdu_name] = cooling_water_supply_temperature_sp
            cdu_chilled_water_supply_temperatures[cdu_name] = chilled_water_supply_temperature

        return self.sim(
            server_powers=server_powers,
            server_mass_flow_rates=server_mass_flow_rates,
            server_liquid_cooling_percentages=server_liquid_cooling_percentages,
            cooling_water_supply_temperature_sps=cdu_cooling_water_supply_temperature_sps,
            chilled_water_supply_temperatures=cdu_chilled_water_supply_temperatures,
        )
