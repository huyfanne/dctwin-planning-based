from typing import Dict, Tuple

import torch.nn as nn
from dclib import Building

from dctwin.models.cooling.loops import AirLoopManager
from dctwin.models.cooling.loops.chw_loop import CHWLoopManager
from dctwin.models.cooling.loops.cw_loop import CWLoopManager

from dctwin.data import Batch
from dctwin.models.heat_gains import HeatLoadManager


from CoolProp.CoolProp import PropsSI

from dclib import Room
from dclib.data import Inputs

from dctwin.models.cooling.facilities.cdu import CDUModel


class AirWaterCoolingComposite(nn.Module):
    """
    Implement the high-level management routine of the physics-informed ML building simulation framework.
    The framework can take the control signals as input and output the building response.
    The framework consists of two parts: the building model that defines the cooling system topology and the learning
    algorithm that can assimilate data into the device performance model.
    """
    def __init__(
        self,
        building: Building,
        device_key_mapping: Dict
    ):
        super(AirWaterCoolingComposite, self).__init__()
        self.building = building
        self.device_key_mapping = device_key_mapping
        self.heat_load_manager = HeatLoadManager(
            zones=self.building.constructions.zones,
            device_key_mapping=self.device_key_mapping
        )
        self.air_loop_manager = AirLoopManager(
            zones=self.building.constructions.zones,
            device_key_mapping=self.device_key_mapping
        )
        self.chw_loop_manager = CHWLoopManager(
            zones=self.building.constructions.zones,
            chw_loops=self.building.constructions.plant.chilled_water_loops,
            device_key_mapping=self.device_key_mapping
        )
        self.cw_loop_manager = CWLoopManager(
            cw_loops=self.building.constructions.plant.condenser_water_loops,
            device_key_mapping=self.device_key_mapping
        )
        self._init_log_dict()

    def _init_log_dict(self):
        self.simulation_results = {
            "zones": {},
            "acus": {},
            "chilled water pumps": {},
            "chillers": {},
            "condenser water pumps": {},
            "cooling towers": {},
            "total it power": [],
            "total hvac power": [],
            "total dc power": [],
        }
        for zone_name in self.device_key_mapping["zones"].keys():
            self.simulation_results["zones"][zone_name.lower()] = {
                "zone air temperature": [],
                "zone ite inlet temperature": [],
            }
        for acu_name in self.device_key_mapping["acus"].keys():
            self.simulation_results["acus"][acu_name.lower()] = {
                "fan": {
                    "air mass flow rate": [],
                    "power": []
                }
            }
        for pump_name in self.device_key_mapping["chilled water pumps"].keys():
            self.simulation_results["chilled water pumps"][pump_name.lower()] = {
                "mass flow rate": [],
                "power": []
            }
        for chiller_name in self.device_key_mapping["chillers"].keys():
            self.simulation_results["chillers"][chiller_name.lower()] = {
                "cooling load": [],
                "chilled water supply temperature": [],
                "condenser water supply temperature": [],
                "power": []
            }
        for pump_name in self.device_key_mapping["condenser water pumps"].keys():
            self.simulation_results["condenser water pumps"][pump_name.lower()] = {
                "mass flow rate": [],
                "power": []
            }
        for tower_name in self.device_key_mapping["cooling towers"].keys():
            self.simulation_results["cooling towers"][tower_name.lower()] = {
                "return water temperature": [],
                "water mass flow rate": [],
                "supply water temperature": [],
                "cooling tower air flow rate ratio": [],
                "outside air wetbulb temperature": [],
                "cooling load": [],
                "power": [],
            }

    @staticmethod
    def _summary(
        zone_heat_loads: Batch,
        air_loop_simulation_results: Batch,
        chw_loop_simulation_results,
        cw_loop_simulation_results: Batch,
    ):
        # calculate the facility hvac power
        facility_hvac_power = 0.0
        for zone_name, fan_power in air_loop_simulation_results.acu_property.fan_powers.items():
            facility_hvac_power += fan_power.view(-1)
        for pump_name, chilled_water_pump_property in chw_loop_simulation_results.chilled_water_pump_property.items():
            facility_hvac_power += chilled_water_pump_property.power.view(-1)
        for chiller_name, chiller_property in chw_loop_simulation_results.chiller_property.items():
            facility_hvac_power += chiller_property.power.view(-1)
        for pump_name, condenser_water_pump_property in cw_loop_simulation_results.condenser_water_pump_property.items():
            facility_hvac_power += condenser_water_pump_property.power.view(-1)
        for tower_name, cooling_tower_property in cw_loop_simulation_results.cooling_tower_property.items():
            facility_hvac_power += cooling_tower_property.power.view(-1)

        # fetch the DC IT equipment power
        ite_power = 0.0
        for zone_name, it_load in zone_heat_loads.zone_ite_heat_loads.items():
            ite_power += it_load

        # get the total power consumption of a DC
        total_power = facility_hvac_power + ite_power

        return Batch(
            facility_hvac_power=facility_hvac_power,
            ite_power=ite_power,
            total_power=total_power
        )

    def log(
        self,
        air_loop_simulation_results: Batch,
        chw_loop_simulation_results: Batch,
        cw_loop_simulation_results: Batch,
        summary: Batch
    ):
        for zone_name in self.device_key_mapping["zones"].keys():
            self.simulation_results["zones"][zone_name.lower()]["zone air temperature"].append(
                air_loop_simulation_results.zone_air_temperatures[zone_name.lower()].item()
            )
            self.simulation_results["zones"][zone_name.lower()]["zone ite inlet temperature"].append(
                air_loop_simulation_results.zone_ite_inlet_temperatures[zone_name.lower()].item()
            )
        for acu_name in self.device_key_mapping["acus"].keys():
            self.simulation_results["acus"][acu_name.lower()]["fan"]["air mass flow rate"].append(
                air_loop_simulation_results.acu_property.air_mass_flow_rates[acu_name.lower()].item()
            )
            self.simulation_results["acus"][acu_name.lower()]["fan"]["power"].append(
                air_loop_simulation_results.acu_property.fan_powers[acu_name.lower()].item()
            )
        for pump_name in self.device_key_mapping["chilled water pumps"].keys():
            self.simulation_results["chilled water pumps"][pump_name.lower()]["mass flow rate"].append(
                chw_loop_simulation_results.chilled_water_pump_property[pump_name.lower()].mass_flow_rate.item()
            )
            self.simulation_results["chilled water pumps"][pump_name.lower()]["power"].append(
                chw_loop_simulation_results.chilled_water_pump_property[pump_name.lower()].power.item()
            )
        for chiller_name in self.device_key_mapping["chillers"].keys():
            self.simulation_results["chillers"][chiller_name.lower()]["cooling load"].append(
                chw_loop_simulation_results.chiller_property[chiller_name.lower()].cooling_load.item()
            )
            self.simulation_results["chillers"][chiller_name.lower()]["chilled water supply temperature"].append(
                chw_loop_simulation_results.chiller_property[chiller_name.lower()].chilled_water_temperature.item()
            )
            self.simulation_results["chillers"][chiller_name.lower()]["condenser water supply temperature"].append(
                chw_loop_simulation_results.chiller_property[chiller_name.lower()].condenser_water_temperature.item()
            )
            self.simulation_results["chillers"][chiller_name.lower()]["power"].append(
                chw_loop_simulation_results.chiller_property[chiller_name.lower()].power.item()
            )
        for pump_name in self.device_key_mapping["condenser water pumps"].keys():
            self.simulation_results["condenser water pumps"][pump_name.lower()]["mass flow rate"].append(
                cw_loop_simulation_results.condenser_water_pump_property[pump_name.lower()].mass_flow_rate.item()
            )
            self.simulation_results["condenser water pumps"][pump_name.lower()]["power"].append(
                cw_loop_simulation_results.condenser_water_pump_property[pump_name.lower()].power.item()
            )
        for tower_name in self.device_key_mapping["cooling towers"].keys():
            self.simulation_results["cooling towers"][tower_name.lower()]["cooling load"].append(
                cw_loop_simulation_results.cooling_tower_property[tower_name.lower()].cooling_load.item()
            )
            self.simulation_results["cooling towers"][tower_name.lower()]["power"].append(
                cw_loop_simulation_results.cooling_tower_property[tower_name.lower()].power.item()
            )
        # fill in summary information
        self.simulation_results["total it power"].append(summary.ite_power.item())
        self.simulation_results["total hvac power"].append(summary.facility_hvac_power.item())
        self.simulation_results["total dc power"].append(summary.total_power.item())

    def collect(self, data: dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        self.air_loop_manager.collect(data=data)
        self.chw_loop_manager.collect(data=data)
        self.cw_loop_manager.collect(data=data)

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        self.air_loop_manager.learn()
        self.chw_loop_manager.learn()
        self.cw_loop_manager.learn()

    def sim_thermal_loads(
        self,
        external_inputs: Batch,
    ):
        ite_heat_load = self.heat_load_manager(
            cpu_load_schedule=external_inputs.cpu_load_schedule
        )
        return ite_heat_load

    def sim_hvac(
        self,
        zone_heat_loads: Batch,
        external_inputs: Batch,
        acts: Batch,
    ) -> Tuple[Batch, Batch, Batch, Batch]:
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        air_loop_simulation_results = self.air_loop_manager(
            heat_loads=zone_heat_loads.zone_ite_heat_loads,
            acu_controls=acts.zones
        )
        chw_loop_simulation_results = self.chw_loop_manager.forward(
            plant_control_inputs=acts.plants,
            acu_simulation_results=air_loop_simulation_results.acu_property
        )
        cw_loop_simulation_results = self.cw_loop_manager(
            plant_control_inputs=acts.plants,
            chw_loop_simulation_results=chw_loop_simulation_results,
            weather=external_inputs.weather
        )
        summary = self._summary(
            zone_heat_loads=zone_heat_loads,
            air_loop_simulation_results=air_loop_simulation_results,
            chw_loop_simulation_results=chw_loop_simulation_results,
            cw_loop_simulation_results=cw_loop_simulation_results
        )
        return air_loop_simulation_results, chw_loop_simulation_results, cw_loop_simulation_results, summary


class LiquidCoolingComposite:
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
    ):
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
        cooling_water_supply_temperature_sp = self.inputs.cdus[cdu_name].cooling_water_supply_temperature_sp
        chilled_water_supply_temperature = self.inputs.cdus[cdu_name].chilled_water_supply_temperature
        chilled_water_mass_flow_rate = None
        for rack_name in self.room.constructions.cdus[cdu_name].meta.racks:
            for server_name, server in self.room.constructions.racks[rack_name].constructions.servers.items():
                server_powers[server_name] = \
                    self.inputs.servers[server_name].input_power
                server_mass_flow_rates[server_name] = \
                    self.inputs.servers[server_name].liquid_mass_flow_rate
                server_liquid_cooling_percentages[server_name] = \
                    self.inputs.servers[server_name].liquid_percentage
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
        server_powers: Dict[str, float],
        server_mass_flow_rates: Dict[str, float],
        server_liquid_cooling_percentages: Dict[str, float],
        cooling_water_supply_temperature_sps: Dict[str, float],
        chilled_water_supply_temperatures: Dict[str, float],
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
