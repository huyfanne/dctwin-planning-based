from typing import Dict

import torch
import torch.nn as nn
from dclib.room import Room
from dclib.cooling.plant.loops import ChilledWaterLoops

from ....data.batch import Batch
from ....models.cooling.facilities import HeatExchanger, ChillerModel, PumpModel
from .ds import BranchData

from dcdyn.utils.const import cp_water


class CHWLoopManager(nn.Module):
    def __init__(
        self,
        zones: Dict[str, Room],
        chw_loops: Dict[str, ChilledWaterLoops],
        device_key_mapping: Dict
    ):
        super(CHWLoopManager, self).__init__()
        self.zones = zones
        self.chw_loops = chw_loops
        self.device_key_mapping = device_key_mapping
        self.models = self._init_models()

    def _init_models(self):
        """
        Initialize the learnable models for the chilled water loops
        """
        chw_loop_models = {}
        # get the model of each plant equipments of the building
        for chw_loop_name, chw_loop in self.chw_loops.items():
            # get the model of the plant
            chw_loop_models[chw_loop_name] = {
                "supply_branches": {},
                "demand_branches": {},
            }
            for supply_branch_name, supply_branch in chw_loop.supply_branches.items():
                chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name] = {
                    "side": supply_branch.side,
                }
                if supply_branch.components.heat_exchangers is not None:
                    for heat_exchanger_name, heat_exchanger in supply_branch.components.heat_exchangers.items():
                        chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["heat_exchanger"] = \
                            HeatExchanger(
                                config=heat_exchanger,
                                key_mapping=self.device_key_mapping["heat exchangers"][heat_exchanger_name],
                                internal_fluid_name="water",
                                external_fluid_name="water"
                            )
                        self.add_module(
                            f"{heat_exchanger.uid} heat exchanger",
                            chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["heat_exchanger"]
                        )
                if supply_branch.components.chillers is not None:
                    for chiller_name, chiller in supply_branch.components.chillers.items():
                        chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["chiller"] = ChillerModel(
                            config=chiller,
                            key_mapping=self.device_key_mapping["chillers"][chiller_name]
                        )
                        self.add_module(
                            chiller_name,
                            chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["chiller"]
                        )
                if supply_branch.components.pumps is not None:
                    for pump_name, pump in supply_branch.components.pumps.items():
                        chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["pump"] = PumpModel(
                            config=pump,
                            key_mapping=self.device_key_mapping["chilled water pumps"][pump_name]
                        )
                        self.add_module(
                            pump_name,
                            chw_loop_models[chw_loop_name]["supply_branches"][supply_branch_name]["pump"]
                        )
            for demand_branch_name, demand_branch in chw_loop.demand_branches.items():
                chw_loop_models[chw_loop_name]["demand_branches"][demand_branch_name] = {
                    "side": demand_branch.side,
                }
                if demand_branch.components.pumps is not None:
                    for pump_name, pump in demand_branch.components.pumps.items():
                        chw_loop_models[chw_loop_name]["demand_branches"][demand_branch_name]["pump"] = PumpModel(
                            config=pump,
                            key_mapping=self.device_key_mapping["chilled water pumps"][pump_name]
                        )
                        self.add_module(
                            pump_name,
                            chw_loop_models[chw_loop_name]["demand_branches"][demand_branch_name]["pump"]
                        )
                if demand_branch.components.acu is not None:
                    for acu_name, acu in demand_branch.components.acu.items():
                        chw_loop_models[chw_loop_name]["demand_branches"][demand_branch_name]["coil"] =\
                            HeatExchanger(
                                config=acu,
                                key_mapping=self.device_key_mapping["acus"][acu_name]["cooling coil"],
                                internal_fluid_name="water",
                                external_fluid_name="air"
                            )
                        self.add_module(
                            f"{acu.uid} cooling coil",
                            chw_loop_models[chw_loop_name]["demand_branches"][demand_branch_name]["coil"]
                        )
        return chw_loop_models

    def _sim(
        self,
        plant_control_inputs: Batch,
        zone_control_inputs: Batch,
        air_loop_simulation_results: Batch,
    ):
        # cooling coil property
        acu_property = {}
        chilled_water_pump_property = {}
        chiller_property = {}
        branch_fluid_properties = Batch(
            supply={},
            demand={},
        )
        # Set loop exiting temperature according to the control inputs
        for chilled_water_loop_name, chilled_water_loop in self.models.items():
            control = plant_control_inputs[chilled_water_loop_name]
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if supply_branch["side"] == "outlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=control["supply_sp"],
                        inlet_mass_flow_rate=0,
                        outlet_temperature=control["supply_sp"],
                        outlet_mass_flow_rate=0,
                    )
        # Demand-side fluid property simulation of the chilled water loop
        total_demand_loop_m = 0
        weighted_return_temperature = 0
        num_middle_branches = 0
        total_cooling_load = 0
        for chilled_water_loop_name, chilled_water_loop in self.models.items():
            # get the setpoint of the chilled water loop
            chw_sp = plant_control_inputs[chilled_water_loop_name]["supply_sp"].view(-1, 1)
            # for the demand-side, we start with the middle branches that contain the cooling coils
            for demand_branch_name, demand_branch in chilled_water_loop["demand_branches"].items():
                if demand_branch["side"] == "middle":
                    coil_model = demand_branch["coil"]
                    # first locate the cooling coil, identifying its ACU and the zone that hosts the ACU
                    supply_air_sp = zone_control_inputs[coil_model.uid].supply_air_temperature
                    supply_air_flow_rate = zone_control_inputs[coil_model.uid].supply_air_mass_flow_rate
                    inlet_air_temperature = air_loop_simulation_results.acu_property.return_air_temperatures[
                        coil_model.uid
                    ]
                    # simulate the required chilled water mass flow rate of the cooling coil
                    if torch.isclose(supply_air_flow_rate, torch.tensor(0.0)):
                        water_mass_flow_rate = torch.tensor(0.0)
                        heat_transfer_rate = torch.tensor(0.0)
                    else:
                        water_mass_flow_rate, heat_transfer_rate, supply_air_temperature = coil_model.solve(
                            T_air_in=inlet_air_temperature,
                            m_air=supply_air_flow_rate,
                            T_water_in=chw_sp,
                            T_air_out_sp=supply_air_sp
                        )
                    # record the cooling coil property
                    acu_property[coil_model.uid] = Batch(
                        sensible_heat_transfer_rate=heat_transfer_rate,
                        water_mass_flow_rate=water_mass_flow_rate,
                    )
                    # simulate the return temperature of a cooling coil
                    if torch.isclose(water_mass_flow_rate, torch.tensor(0.0)):
                        return_temp = chw_sp
                    else:
                        return_temp = chw_sp + heat_transfer_rate / (
                            water_mass_flow_rate * cp_water
                        )
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=chw_sp,
                        inlet_mass_flow_rate=water_mass_flow_rate,
                        outlet_temperature=return_temp,
                        outlet_mass_flow_rate=water_mass_flow_rate,
                    )
                    # update the total demand-side mass flow rate and the weighted return temperature
                    total_demand_loop_m += water_mass_flow_rate
                    weighted_return_temperature += return_temp * water_mass_flow_rate
                    num_middle_branches += 1
                    # the cooling load that should be met by the chiller plant is equal to IT power and CRAH power
                    total_cooling_load += (
                        heat_transfer_rate + air_loop_simulation_results.acu_property.fan_powers[coil_model.uid]
                    )

            # calculate average return temperature
            average_return_temperature = chw_sp + total_cooling_load / (cp_water * total_demand_loop_m)

            # after we simulate the cooling coil branches, we simulate the inlet and outlet branches
            for demand_branch_name, demand_branch in chilled_water_loop["demand_branches"].items():
                if demand_branch["side"] == "outlet":
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=average_return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=average_return_temperature,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )
                if demand_branch["side"] == "inlet":
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=chw_sp,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=chw_sp,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )

            # supply-side fluid property simulation of the chilled water loop
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if supply_branch["side"] == "inlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=average_return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=average_return_temperature,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )
                if supply_branch["side"] == "middle":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=average_return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m/4,
                        outlet_temperature=chw_sp,
                        outlet_mass_flow_rate=total_demand_loop_m/4,
                    )
                if supply_branch["side"] == "outlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=chw_sp,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=chw_sp,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )

            # distribute cooling load to each chiller according to the uniform load schedule
            num_chiller = 0
            chiller_cooling_loads = {}
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if "chiller" in supply_branch.keys():
                    num_chiller += 1
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if "chiller" in supply_branch.keys():
                    chiller_model = supply_branch["chiller"]
                    chiller_cooling_loads[chiller_model.uid] = total_cooling_load / num_chiller
                    branch_fluid_properties["supply"][supply_branch_name].set_inlet(
                        temperature=average_return_temperature,
                        mass_flow_rate=total_demand_loop_m / num_chiller
                    )
                    branch_fluid_properties["supply"][supply_branch_name].set_outlet(
                        temperature=chw_sp,
                        mass_flow_rate=total_demand_loop_m / num_chiller
                    )
            # Equipment power consumption simulation of the chilled water loop
            for demand_branch_name, demand_branch in chilled_water_loop["demand_branches"].items():
                if "pump" in demand_branch.keys():
                    pump_model = demand_branch["pump"]
                    chilled_water_pump_property[pump_model.uid] = Batch(
                        mass_flow_rate=branch_fluid_properties["supply"][demand_branch_name].inlet_M,
                        power=pump_model(branch_fluid_properties["supply"][demand_branch_name].inlet_M)
                    )
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if "pump" in supply_branch.keys():
                    pump_model = supply_branch["pump"]
                    chilled_water_pump_property[pump_model.uid] = Batch(
                        mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].inlet_M,
                        power=pump_model(branch_fluid_properties["supply"][supply_branch_name].inlet_M)
                    )
                if "chiller" in supply_branch.keys():
                    chiller_model = supply_branch["chiller"]
                    power = chiller_model(
                        cooling_load=chiller_cooling_loads[chiller_model.uid],
                        chw_sp=chw_sp,
                        cw_sp=plant_control_inputs["condenser water loop"]["supply_sp"],
                    )
                    chiller_property[chiller_model.uid] = Batch(
                        cooling_load=chiller_cooling_loads[chiller_model.uid],
                        power=power,
                        chilled_water_temperature=chw_sp,
                        condenser_water_temperature=plant_control_inputs["condenser water loop"]["supply_sp"],
                    )
        return Batch(acu_property), Batch(chilled_water_pump_property), Batch(chiller_property)

    def collect(self, data: dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        # feed online data to the chilled water loop equipment models
        for chw_loop_name, chw_loop_models in self.models.items():
            # demand-side data collection
            for demand_branch_name, demand_branch_models in chw_loop_models["demand_branches"].items():
                if "pump" in demand_branch_models.keys():
                    demand_branch_models["pump"].collect(data)
                if "coil" in demand_branch_models.keys():
                    demand_branch_models["coil"].collect(data)
            # supply-side data collection
            for supply_branch_name, supply_branch_models in chw_loop_models["supply_branches"].items():
                if "pump" in supply_branch_models.keys():
                    supply_branch_models["pump"].collect(data)
                if "chiller" in supply_branch_models.keys():
                    supply_branch_models["chiller"].collect(data)

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        # learn the chilled water loop equipment models
        for chw_loop_name, chw_loop_models in self.models.items():
            # learn the chiller performance model
            for supply_branch_name, supply_branch_models in chw_loop_models["supply_branches"].items():
                if "chiller" in supply_branch_models.keys():
                    supply_branch_models["chiller"].learn()
                if "pump" in supply_branch_models.keys():
                    supply_branch_models["pump"].learn()
            # learn the cooling coil performance model
            for demand_branch_name, demand_branch_models in chw_loop_models["demand_branches"].items():
                if "coil" in demand_branch_models.keys():
                    demand_branch_models["coil"].learn()
                if "pump" in demand_branch_models.keys():
                    demand_branch_models["pump"].learn()

    def forward(
        self,
        zone_control_inputs: Batch,
        plant_control_inputs: Batch,
        air_loop_simulation_results: Batch,
    ) -> Batch:
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        acu_property, chilled_water_pump_property, chiller_property = self._sim(
            zone_control_inputs=zone_control_inputs,
            plant_control_inputs=plant_control_inputs,
            air_loop_simulation_results=air_loop_simulation_results,
        )
        return Batch(
            acu_property=acu_property,
            chilled_water_pump_property=chilled_water_pump_property,
            chiller_property=chiller_property,
        )
