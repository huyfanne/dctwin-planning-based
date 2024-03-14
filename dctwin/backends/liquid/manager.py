from typing import Dict
from CoolProp.CoolProp import PropsSI

from dclib import Room
from loguru import logger

from .cdu import CoolantDistributionUnit


class LiquidCoolingManager:
    """
    Implement the liquid cooling manager to simulate the thermal properties and the electrical power consumption
    of a hybrid cooling system with the direct-to-chip cooling system and conventional force ventilation air cooling
    system.
    """
    def __init__(
        self,
        room: Room,
        cpu_number_per_server=8,
        fluid_name='water'
    ):
        self.room = room
        self.cdus = self._make_cdus()
        self.racks = room.constructions.racks
        self.fluid_name = fluid_name
        self.cpu_number_per_server = cpu_number_per_server
        self.liquid_capacity = PropsSI('C', 'P', 101325, 'Q', 0, "water")  # J/kg/K

        # solver parameters
        self.tol = 1e-2
        self.max_iter = 50

        # set the initial cooling water supply temperature
        self.cooling_water_supply_temperature = {cdu_name: 25 for cdu_name in self.cdus.keys()}

    def _make_cdus(self) -> dict[str, CoolantDistributionUnit]:
        """
        Create the CDU instances according to the room configuration.
        """
        cdus = {}
        for cdu_name, cdu in self.room.constructions.cdus.items():
            # search for the racks that are under the control of the current CDU
            racks = {}
            for rack_name in cdu.meta.racks:
                racks[rack_name] = self.room.constructions.racks[rack_name]
            cdus[cdu_name] = CoolantDistributionUnit(
                cdu=cdu,
                racks=racks,
            )
        return cdus

    def _formatted_cdu_inputs(self, cdu_name: str):
        server_powers = {}
        server_mass_flow_rates = {}
        server_liquid_cooling_percentages = {}
        cooling_water_supply_temperature_sp = self.room.inputs.cdus[cdu_name].cooling_water_supply_temperature_sp
        cooling_water_supply_temperature = self.cooling_water_supply_temperature
        chilled_water_supply_temperature = self.room.inputs.cdus[cdu_name].chilled_water_supply_temperature
        chilled_water_mass_flow_rate = None
        for rack_name in self.room.constructions.cdus[cdu_name].meta.racks:
            for server_name, server in self.room.constructions.racks[rack_name].constructions.servers.items():
                server_powers[server_name] = \
                    self.room.inputs.servers[server_name].input_power
                server_mass_flow_rates[server_name] = \
                    self.room.inputs.servers[server_name].liquid_mass_flow_rate * 1000
                server_liquid_cooling_percentages[server_name] = \
                    self.room.inputs.servers[server_name].liquid_percentage
        return (
            server_powers,
            server_mass_flow_rates,
            server_liquid_cooling_percentages,
            cooling_water_supply_temperature,
            cooling_water_supply_temperature_sp,
            chilled_water_supply_temperature,
            chilled_water_mass_flow_rate,
        )

    def sim(
        self,
        server_powers: Dict[str, float],
        server_mass_flow_rates: Dict[str, float],
        server_liquid_cooling_percentages: Dict[str, float],
        cooling_water_supply_temperature_sps: Dict[str, float],
        chilled_water_supply_temperatures: Dict[str, float],
        chilled_water_mass_flow_rates: Dict[str, float | None] = None,
    ):
        cdu_electrical_powers = {}
        cdu_chilled_water_return_temperatures = {}
        cdu_cooling_water_supply_temperatures = {}
        cdu_cooling_water_return_temperatures = {}
        cdu_chilled_water_mass_flow_rates = {}
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
            cooling_water_supply_temperature_sp = cooling_water_supply_temperature_sps[cdu_name]
            chilled_water_supply_temperature = chilled_water_supply_temperatures[cdu_name]
            chilled_water_mass_flow_rate = chilled_water_mass_flow_rates[cdu_name]
            if chilled_water_mass_flow_rate is None and cooling_water_supply_temperature_sp is not None:
                # bi-section loop to determine the chilled water mass flow rate
                cooling_water_supply_temperature = cooling_water_supply_temperature_sp + 1
                m_water_min = 0
                m_water_max = sum(current_server_mass_flow_rates.values())
                m_water = (m_water_min + m_water_max) / 2
                (
                    cdu_electrical_power,
                    chilled_water_return_temperature,
                    cooling_water_supply_temperature,
                    cdu_return_temperature,
                    chilled_water_mass_flow_rate,
                    hx_info
                ) = cdu.sim(
                    server_powers=current_server_powers,
                    server_mass_flow_rates=current_server_mass_flow_rates,
                    server_liquid_cooling_percentages=current_server_liquid_cooling_percentages,
                    chilled_water_supply_temperature=chilled_water_supply_temperature,
                    cooling_water_supply_temperature=cooling_water_supply_temperature,
                    chilled_water_mass_flow_rate=m_water,
                )
                # print(
                #     f"iteration: 0, T_sup: {cooling_water_supply_temperature:.2f}, "
                #     f"T_ret: {cdu_return_temperature:.2f}, M_sup: {sum(current_server_mass_flow_rates.values()):.2f}, Q={sum(current_server_powers.values()):.2f},"
                #     f" m_water: {m_water:.5f}, m_water_min: {m_water_min:.5f}, m_water_max: {m_water_max:.5f}")
                for iteration in range(1, self.max_iter + 1):
                    if cooling_water_supply_temperature > cooling_water_supply_temperature_sp:
                        m_water_min = m_water
                    else:
                        m_water_max = m_water
                    m_water = (m_water_min + m_water_max) / 2
                    (
                        cdu_electrical_power,
                        chilled_water_return_temperature,
                        cooling_water_supply_temperature,
                        cdu_return_temperature,
                        chilled_water_mass_flow_rate,
                        hx_info
                    ) = cdu.sim(
                        server_powers=current_server_powers,
                        server_mass_flow_rates=current_server_mass_flow_rates,
                        server_liquid_cooling_percentages=current_server_liquid_cooling_percentages,
                        chilled_water_supply_temperature=chilled_water_supply_temperature,
                        cooling_water_supply_temperature=cooling_water_supply_temperature,
                        chilled_water_mass_flow_rate=m_water,
                    )
                    # print(
                    #     f"iteration: {iteration}, T_sup: {cooling_water_supply_temperature:.2f}, "
                    #     f"T_ret: {cdu_return_temperature:.2f}, M_sup: {sum(current_server_mass_flow_rates.values()):.2f}, Q={sum(current_server_powers.values()):.2f},"
                    #     f" m_water: {m_water:.5f}, m_water_min: {m_water_min:.5f}, m_water_max: {m_water_max:.5f}")
                    if abs(cooling_water_supply_temperature - cooling_water_supply_temperature_sp) < self.tol:
                        break
                    if iteration == self.max_iter:
                        logger.warning(
                            f"{cdu_name}'s heat exchanger root finding cannot find root at iteration {iteration}."
                        )
            elif chilled_water_mass_flow_rate is not None:
                cooling_water_supply_temperature = self.cooling_water_supply_temperature[cdu_name]
                (
                    cdu_electrical_power,
                    chilled_water_return_temperature,
                    cooling_water_supply_temperature,
                    cdu_return_temperature,
                    chilled_water_mass_flow_rate,
                    hx_info
                ) = cdu.sim(
                    server_powers=server_powers,
                    server_mass_flow_rates=server_mass_flow_rates,
                    server_liquid_cooling_percentages=server_liquid_cooling_percentages,
                    chilled_water_supply_temperature=chilled_water_supply_temperature,
                    cooling_water_supply_temperature=cooling_water_supply_temperature,
                    chilled_water_mass_flow_rate=chilled_water_mass_flow_rate,
                )
            else:
                raise ValueError(
                    "For heat exchangers, either outer outlet temperature setpoint"
                    " or chilled water mass flow rate should be provided.")
            # update cooling water supply temperature
            self.cooling_water_supply_temperature[cdu_name] = cooling_water_supply_temperature
            # update cdu simulation results
            cdu_electrical_powers[cdu_name] = cdu_electrical_power
            cdu_chilled_water_return_temperatures[cdu_name] = chilled_water_return_temperature
            cdu_cooling_water_supply_temperatures[cdu_name] = cooling_water_supply_temperature
            cdu_cooling_water_return_temperatures[cdu_name] = cdu_return_temperature
            cdu_chilled_water_mass_flow_rates[cdu_name] = chilled_water_mass_flow_rate
            cdu_hx_infos[cdu_name] = hx_info

        return (
            cdu_electrical_powers,
            cdu_chilled_water_return_temperatures,
            cdu_cooling_water_supply_temperatures,
            cdu_cooling_water_return_temperatures,
            cdu_chilled_water_mass_flow_rates,
            cdu_hx_infos
        )
