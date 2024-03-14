from CoolProp.CoolProp import PropsSI

from dclib import Room

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
        self.liquid_capacity = PropsSI('C', 'P', 101325, 'T', 300, self.fluid_name)

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

    def sim(self):
        cdu_electrical_powers = {}
        cdu_chilled_water_return_temperatures = {}
        cdu_cooling_water_supply_temperatures = {}
        cdu_return_temperatures = {}
        cdu_chilled_water_mass_flow_rates = {}
        cdu_hx_infos = {}
        for cdu_name, cdu in self.cdus.items():
            # fetch the server power and mass flow rate of the current rack
            server_powers = {}
            server_mass_flow_rates = {}
            server_liquid_cooling_percentages = {}
            for rack_name in self.room.constructions.cdus[cdu_name].meta.racks:
                for server_name, server in self.room.constructions.racks[rack_name].constructions.servers.items():
                    server_powers[server_name] =\
                        self.room.inputs.servers[server_name].input_power
                    server_mass_flow_rates[server_name] =\
                        self.room.inputs.servers[server_name].liquid_mass_flow_rate * 1000
                    server_liquid_cooling_percentages[server_name] =\
                        self.room.inputs.servers[server_name].liquid_percentage
            (cdu_electrical_power, chilled_water_return_temperature, cooling_water_supply_temperature,
             cdu_return_temperature, chilled_water_mass_flow_rate, hx_info) = cdu.sim(
                cooling_water_supply_temperature=self.room.inputs.cdus[cdu_name].supply_water_temperature,
                server_powers=server_powers,
                server_mass_flow_rates=server_mass_flow_rates,
                server_liquid_cooling_percentages=server_liquid_cooling_percentages,
                chilled_water_supply_temperature=20,
                chilled_water_mass_flow_rate=None,
                cooling_water_supply_temperature_sp=25
            )
            # store the results
            cdu_electrical_powers[cdu_name] = cdu_electrical_power
            cdu_chilled_water_return_temperatures[cdu_name] = chilled_water_return_temperature
            cdu_cooling_water_supply_temperatures[cdu_name] = cooling_water_supply_temperature
            cdu_return_temperatures[cdu_name] = cdu_return_temperature
            cdu_chilled_water_mass_flow_rates[cdu_name] = chilled_water_mass_flow_rate
            cdu_hx_infos[cdu_name] = hx_info

        return (
            cdu_electrical_powers,
            cdu_chilled_water_return_temperatures,
            cdu_cooling_water_supply_temperatures,
            cdu_return_temperatures,
            cdu_chilled_water_mass_flow_rates,
            cdu_hx_infos
        )
