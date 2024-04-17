from typing import Dict, Tuple

import torch.nn as nn
from dclib import Building

from .air_loop import AirLoopManager
from .chw_loop import CHWLoopManager
from .cw_loop import CWLoopManager

from ....data import Batch
from ....models.heat_gains import HeatLoadManager


class PIDTManager(nn.Module):
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
        super(PIDTManager, self).__init__()
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
            "acus": {},
            "chilled water pumps": {},
            "chillers": {},
            "condenser water pumps": {},
            "cooling towers": {},
            "total it power": [],
            "total hvac power": [],
            "total dc power": [],
        }
        for acu_name in self.device_key_mapping["acus"].keys():
            self.simulation_results["acus"][acu_name] = {
                "fan": {
                    "air mass flow rate": [],
                    "power": []
                }
            }
        for pump_name in self.device_key_mapping["chilled water pumps"].keys():
            self.simulation_results["chilled water pumps"][pump_name] = {
                "mass flow rate": [],
                "power": []
            }
        for chiller_name in self.device_key_mapping["chillers"].keys():
            self.simulation_results["chillers"][chiller_name] = {
                "cooling load": [],
                "chilled water supply temperature": [],
                "condenser water supply temperature": [],
                "power": []
            }
        for pump_name in self.device_key_mapping["condenser water pumps"].keys():
            self.simulation_results["condenser water pumps"][pump_name] = {
                "mass flow rate": [],
                "power": []
            }
        for tower_name in self.device_key_mapping["cooling towers"].keys():
            self.simulation_results["cooling towers"][tower_name] = {
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
            facility_hvac_power += fan_power
        for pump_name, chilled_water_pump_property in chw_loop_simulation_results.chilled_water_pump_property.items():
            facility_hvac_power += chilled_water_pump_property.power.item()
        for chiller_name, chiller_property in chw_loop_simulation_results.chiller_property.items():
            facility_hvac_power += chiller_property.power
        for pump_name, condenser_water_pump_property in cw_loop_simulation_results.condenser_water_pump_property.items():
            facility_hvac_power += condenser_water_pump_property.power
        for tower_name, cooling_tower_property in cw_loop_simulation_results.cooling_tower_property.items():
            facility_hvac_power += cooling_tower_property.power

        # fetch the DC IT equipment power
        ite_power = 0.0
        for zone_name, it_load in zone_heat_loads.ite_heat_loads.items():
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
        for acu_name in self.device_key_mapping["acus"].keys():
            self.simulation_results["acus"][acu_name]["fan"]["air mass flow rate"].append(
                air_loop_simulation_results.acu_property.air_mass_flow_rates[acu_name].item()
            )
            self.simulation_results["acus"][acu_name]["fan"]["power"].append(
                air_loop_simulation_results.acu_property.fan_powers[acu_name].item()
            )
        for pump_name in self.device_key_mapping["chilled water pumps"].keys():
            self.simulation_results["chilled water pumps"][pump_name]["power"].append(
                chw_loop_simulation_results.chilled_water_pump_property[pump_name].power.item()
            )
        for chiller_name in self.device_key_mapping["chillers"].keys():
            self.simulation_results["chillers"][chiller_name]["cooling load"].append(
                chw_loop_simulation_results.chiller_property[chiller_name].cooling_load.item()
            )
            self.simulation_results["chillers"][chiller_name]["power"].append(
                chw_loop_simulation_results.chiller_property[chiller_name].power.item()
            )
        for pump_name in self.device_key_mapping["condenser water pumps"].keys():
            self.simulation_results["condenser water pumps"][pump_name]["power"].append(
                cw_loop_simulation_results.condenser_water_pump_property[pump_name].power.item()
            )
        for tower_name in self.device_key_mapping["cooling towers"].keys():
            self.simulation_results["cooling towers"][tower_name]["cooling load"].append(
                cw_loop_simulation_results.cooling_tower_property[tower_name].cooling_load.item()
            )
            self.simulation_results["cooling towers"][tower_name]["power"].append(
                cw_loop_simulation_results.cooling_tower_property[tower_name].power.item()
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
            heat_loads=zone_heat_loads.ite_heat_loads,
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
