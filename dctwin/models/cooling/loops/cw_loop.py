from typing import Dict

import torch
import torch.nn as nn
from dclib.cooling.plant.loops import CondenserWaterLoops

from dctwin.models.cooling.facilities import ChillerModel, PumpModel, CoolingTowerModel
from dctwin.utils.const import water_specific_heat, rho_water
from dctwin.data import Batch
from dctwin.models.cooling.ds import BranchData


class CWLoopManager(nn.Module):
    def __init__(
        self,
        cw_loops: Dict[str, CondenserWaterLoops],
        device_key_mapping: Dict
    ):
        super(CWLoopManager, self).__init__()
        self.cw_loops = cw_loops
        self.device_key_mapping = device_key_mapping
        self.models = self._init_models()

    def _init_models(self):
        """
        Initialize the learnable models for the condensing water loops
        """
        cw_loop_models = {}
        # get the model of each plant equipments of the building
        for cw_loop_name, cw_loop in self.cw_loops.items():
            # get the model of the plant
            cw_loop_models[cw_loop_name] = {
                "supply_branches": {},
                "demand_branches": {},
            }
            for supply_branch_name, supply_branch in cw_loop.supply_branches.items():
                cw_loop_models[cw_loop_name]["supply_branches"][supply_branch_name] = {
                    "side": supply_branch.side,
                }
                if supply_branch.components.cooling_towers is not None:
                    for cooling_tower_name, cooling_tower in supply_branch.components.cooling_towers.items():
                        cw_loop_models[cw_loop_name]["supply_branches"][supply_branch_name]["cooling tower"] = \
                            CoolingTowerModel(
                                config=cooling_tower,
                                key_mapping=self.device_key_mapping["cooling towers"][cooling_tower_name],
                                learnable=False  # the cooling tower model is not learnable
                            )
                        self.add_module(
                            cooling_tower_name,
                            cw_loop_models[cw_loop_name]["supply_branches"][supply_branch_name]["cooling tower"]
                        )
                if supply_branch.components.pumps is not None:
                    for pump_name, pump in supply_branch.components.pumps.items():
                        cw_loop_models[cw_loop_name]["supply_branches"][supply_branch_name]["pump"] = PumpModel(
                            config=pump,
                            key_mapping=self.device_key_mapping["condenser water pumps"][pump_name],
                            learnable=False  # condenser water pump model is not learnable
                        )
                        self.add_module(
                            pump_name,
                            cw_loop_models[cw_loop_name]["supply_branches"][supply_branch_name]["pump"]
                        )
            for demand_branch_name, demand_branch in cw_loop.demand_branches.items():
                cw_loop_models[cw_loop_name]["demand_branches"][demand_branch_name] = {
                    "side": demand_branch.side,
                }
                if demand_branch.components.pumps is not None:
                    for pump_name, pump in demand_branch.components.pumps.items():
                        cw_loop_models[cw_loop_name]["demand_branches"][demand_branch_name]["pump"] = PumpModel(
                            config=pump,
                            key_mapping=self.device_key_mapping["condenser water pumps"][pump_name],
                            learnable=False  # condenser water pump model is not learnable
                        )
                        self.add_module(
                            pump_name,
                            cw_loop_models[cw_loop_name]["demand_branches"][demand_branch_name]["pump"]
                        )
                if demand_branch.components.chillers is not None:
                    for chiller_name, chiller in demand_branch.components.chillers.items():
                        cw_loop_models[cw_loop_name]["demand_branches"][demand_branch_name]["chiller"] = ChillerModel(
                            config=chiller,
                            key_mapping=self.device_key_mapping["chillers"][chiller_name],
                            learnable=False  # condenser water pump model is not learnable
                        )
                        self.add_module(
                            chiller_name,
                            cw_loop_models[cw_loop_name]["demand_branches"][demand_branch_name]["chiller"]
                        )
        return cw_loop_models

    def _sim(
        self,
        plant_control_inputs: Batch,
        chw_loop_simulation_results: Batch,
        outside_air_temperature: Batch,
    ):
        """
        Simulate the condensing water loops
        """
        chiller_property = {}
        condenser_water_pump_property = {}
        cooling_tower_property = {}
        branch_fluid_properties = Batch(
            demand=Batch(),
            supply=Batch(),
        )
        # Set loop exiting temperature according to the control inputs
        for condensing_water_loop_name, condensing_water_loop in self.models.items():
            for supply_branch_name, supply_branch in condensing_water_loop["supply_branches"].items():
                if supply_branch["side"] == "outlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=plant_control_inputs[condensing_water_loop_name]["supply_sp"],
                        inlet_mass_flow_rate=0,
                        outlet_temperature=plant_control_inputs[condensing_water_loop_name]["supply_sp"],
                        outlet_mass_flow_rate=0,
                    )
        # Demand-side fluid property simulation of the chilled water loop
        total_demand_loop_m = 0
        num_middle_branches = 0
        total_cooling_load = 0
        return_temperature = 0
        for condensing_water_loop_name, condensing_water_loop in self.models.items():
            # get the setpoint of the chilled water loop
            sp = plant_control_inputs[condensing_water_loop_name]["supply_sp"]
            # for the demand-side, we start with the middle branches that contain the cooling coils
            for demand_branch_name, demand_branch in condensing_water_loop["demand_branches"].items():
                if demand_branch["side"] == "middle":
                    clg_load = chw_loop_simulation_results.chiller_property[
                        demand_branch["chiller"].uid.lower()
                    ].cooling_load
                    # for condenser loop, the chiller condenser flow rate is always equal to the designed flow rate
                    mass_flow_rate = torch.tensor(
                        demand_branch["chiller"].config.cooling.reference_condenser_fluid_flow_rate * rho_water,
                        dtype=torch.float32
                    )
                    total_cooling_load += clg_load
                    total_demand_loop_m += mass_flow_rate
                    return_temperature += (sp + clg_load / (mass_flow_rate * water_specific_heat)) * mass_flow_rate
                    num_middle_branches += 1
            return_temperature /= total_demand_loop_m  # average out over all demand branches w.r.t. branch flow rate

            # after we simulate the cooling coil branches, we simulate the inlet and outlet branches
            for demand_branch_name, demand_branch in condensing_water_loop["demand_branches"].items():
                if demand_branch["side"] == "outlet":
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=return_temperature,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )
                if demand_branch["side"] == "inlet":
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=sp,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=sp,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )

            # Supply-side fluid property simulation of the chilled water loop
            num_cooling_towers = 0
            ct_clg_loads = {}
            for supply_branch_name, supply_branch in condensing_water_loop["supply_branches"].items():
                if "cooling tower" in supply_branch.keys():
                    num_cooling_towers += 1
            for supply_branch_name, supply_branch in condensing_water_loop["supply_branches"].items():
                if supply_branch["side"] == "inlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=return_temperature,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )
                if supply_branch["side"] == "middle":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=return_temperature,
                        inlet_mass_flow_rate=total_demand_loop_m/num_cooling_towers,
                        outlet_temperature=sp,
                        outlet_mass_flow_rate=total_demand_loop_m/num_cooling_towers,
                    )
                if supply_branch["side"] == "outlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=sp,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=sp,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )
            # Distribute cooling load to each cooling tower according to the uniform load workloads
            for supply_branch_name, supply_branch in condensing_water_loop["supply_branches"].items():
                if "cooling tower" in supply_branch.keys():
                    ct_clg_loads[supply_branch["cooling tower"].uid] = (
                        total_cooling_load / num_cooling_towers
                    )
            # Equipment power consumption simulation of the condensing water loop
            for demand_branch_name, demand_branch in condensing_water_loop["demand_branches"].items():
                if "pump" in demand_branch.keys():
                    pump_model = demand_branch["pump"]
                    condenser_water_pump_property[pump_model.uid] = Batch(
                        mass_flow_rate=branch_fluid_properties["supply"][demand_branch_name].inlet_M,
                        power=pump_model(branch_fluid_properties["supply"][demand_branch_name].inlet_M)
                    )
            for supply_branch_name, supply_branch in condensing_water_loop["supply_branches"].items():
                if "pump" in supply_branch.keys():
                    pump_model = supply_branch["pump"]
                    condenser_water_pump_property[pump_model.uid.lower()] = Batch(
                        mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].inlet_M,
                        power=pump_model(branch_fluid_properties["supply"][supply_branch_name].inlet_M)
                    )
                if "cooling tower" in supply_branch.keys():
                    cooling_tower_model = supply_branch["cooling tower"]
                    power = cooling_tower_model(
                        cw_return_water_temperature=branch_fluid_properties["supply"][supply_branch_name].inlet_T,
                        cw_return_water_mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].inlet_M,
                        cw_supply_water_temperature=branch_fluid_properties["supply"][supply_branch_name].outlet_T,
                        outside_air_wetbulb_temperature=outside_air_temperature
                    )
                    cooling_tower_property[cooling_tower_model.uid.lower()] = Batch(
                        return_water_temperature=branch_fluid_properties["supply"][supply_branch_name].inlet_T,
                        return_water_mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].inlet_M,
                        supply_water_temperature=branch_fluid_properties["supply"][supply_branch_name].outlet_T,
                        supply_water_mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].outlet_M,
                        outside_air_wetbulb_temperature=outside_air_temperature,
                        cooling_load=ct_clg_loads[cooling_tower_model.uid],
                        power=power,
                    )
        return condenser_water_pump_property, cooling_tower_property

    def collect(self, data: Batch):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        # feed online data to the condensing water loop equipment models
        for cw_loop_name, cw_loop_models in self.models.items():
            # demand-side equipment data collection
            for demand_branch_name, demand_branch_models in cw_loop_models["demand_branches"].items():
                if "pump" in demand_branch_models.keys():
                    demand_branch_models["pump"].collect(data)
            # supply-side equipment data collection
            for supply_branch_name, supply_branch_models in cw_loop_models["supply_branches"].items():
                if "pump" in supply_branch_models.keys():
                    supply_branch_models["pump"].collect(data)
                if "cooling tower" in supply_branch_models.keys():
                    supply_branch_models["cooling tower"].collect(data)

    def learn(self):
        """
        Learn device models from the collected data
        :return:
        """
        # learn the condensing water loop equipment models
        for cw_loop_name, cw_loop_models in self.models.items():
            # learn the supply-side  condensing water pump performance model
            for supply_branch_name, supply_branch_models in cw_loop_models["supply_branches"].items():
                if "cooling tower" in supply_branch_models.keys():
                    supply_branch_models["cooling tower"].learn()
                if "pump" in supply_branch_models.keys():
                    supply_branch_models["pump"].learn()
            # learn the demand-side condensing water pump performance model
            for demand_branch_name, demand_branch_models in cw_loop_models["demand_branches"].items():
                if "pump" in demand_branch_models.keys():
                    demand_branch_models["pump"].learn()

    def forward(
        self,
        plant_control_inputs: Batch,
        chw_loop_simulation_results: Batch,
        weather: Batch,
    ):
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        condenser_water_pump_property, cooling_tower_property = self._sim(
            plant_control_inputs=plant_control_inputs,
            chw_loop_simulation_results=chw_loop_simulation_results,
            outside_air_temperature=weather.outside_air_temperature,
        )
        return Batch(
            condenser_water_pump_property=condenser_water_pump_property,
            cooling_tower_property=cooling_tower_property,
        )
