from typing import Dict

import torch
import torch.nn as nn
from dclib.room import Room
from dclib.building import Plant

from dclib.cooling.plant.facilities import Components

from dctwin.data.batch import Batch
from dctwin.models.cooling.facilities import (
    HeatExchanger,
    ChillerModel,
    PumpModel,
    ThermalStorageTankModel,
    CoolingTowerModel
)
from dctwin.models.cooling.ds import BranchData

from dctwin.utils.const import water_specific_heat


class PlantManager(nn.Module):
    """
    PlantManager is used to manage the plant loops of the building. It contains the following attributes:
    :param device_key_mapping: the mapping between the device name and the device key
    :param zones: the zones of the building that are connected to the plant loops
    :param chw_loops: the chilled water loops of the building
    :param cw_loops: the condenser water loops of the building
    :param sec_chw_loops: the secondary chilled water loops of the building if any.This is optional.
    """

    def __init__(
            self,
            device_key_mapping: Dict,
            zones: Dict[str, Room],
            plant: Plant,
    ) -> None:

        super(PlantManager, self).__init__()

        self.zones = zones
        self.plant = plant
        self.device_key_mapping = device_key_mapping

        # Initialize the models for the plant loops
        self._init_models()

    def _init_models(self) -> None:

        for loops in [
            self.plant.secondary_chilled_water_loops,
            self.plant.chilled_water_loops,
            self.plant.condenser_water_loops,
        ]:
            for loop_id, loop in loops.items():
                # half-loop demand side components
                for branch_id, branch in loop.demand_branches.items():
                    self._init_facility_models(branch_components=branch.components)
                # half-loop supply side components
                for branch_id, branch in loop.supply_branches.items():
                    self._init_facility_models(branch_components=branch.components)

    def _init_facility_models(
            self,
            branch_components: Components
    ) -> None:

        if branch_components.pipes:
            for component_id, component in branch_components.pipes.items():
                component.model = None
                self.add_module(component_id, component.model)

        if branch_components.pumps:
            for component_id, component in branch_components.pumps.items():
                component.model = PumpModel(
                    config=component,
                    key_mapping=self.device_key_mapping
                )
                self.add_module(component_id, component.model)

        if branch_components.acu:
            for component_id, component in branch_components.acu.items():
                component.model = HeatExchanger(
                    config=component,
                    key_mapping=self.device_key_mapping,
                    internal_fluid_name="water",
                    external_fluid_name="air"
                )

        if branch_components.chillers:
            for component_id, component in branch_components.chillers.items():
                component.model = ChillerModel(
                    config=component,
                    key_mapping=self.device_key_mapping
                )

        if branch_components.tanks:
            for component_id, component in branch_components.tanks.items():
                component.model = ThermalStorageTankModel(
                    config=component,
                    key_mapping=self.device_key_mapping
                )

        if branch_components.cooling_towers:
            for component_id, component in branch_components.cooling_towers.items():
                component.model = CoolingTowerModel(
                    config=component,
                    key_mapping=self.device_key_mapping
                )

        if branch_components.heat_exchangers:
            for component_id, component in branch_components.heat_exchangers.items():
                component.model = HeatExchanger(
                    config=component,
                    key_mapping=self.device_key_mapping,
                    internal_fluid_name="water",
                    external_fluid_name="air"
                )

    def _distribute_heat_load(self, heat_loads: Batch, num_acus: int) -> Dict:
        return {acu_name: heat_loads / num_acus for acu_name in self.chw_loop_models}

    def _sim(
            self,
            plant_control_inputs: Batch,
            acu_simulation_results: Batch
    ):
        # cooling coil property
        acu_property = {}
        chilled_water_pump_property = {}
        chiller_property = {}
        branch_fluid_properties = Batch(
            supply={},
            demand={},
        )
        acu_simulation_results["sensible_heat_transfer_rate"] = Batch()
        acu_simulation_results["water_mass_flow_rate"] = Batch()
        chiller_availability_schedule = plant_control_inputs["chiller availability schedule"]
        # Set loop exiting temperature according to the control inputs
        for chilled_water_loop_name, chilled_water_loop in self.chw_loop_models.items():
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
        for chilled_water_loop_name, chilled_water_loop in self.chw_loop_models.items():
            # get the setpoint of the chilled water loop
            chw_sp = plant_control_inputs[chilled_water_loop_name]["supply_sp"].view(-1, 1)
            # for the demand-side, we start with the middle branches that contain the cooling coils
            for demand_branch_name, demand_branch in chilled_water_loop["demand_branches"].items():
                if demand_branch["side"] == "middle":
                    coil_model = demand_branch["coil"]
                    # first locate the cooling coil, identifying its ACU and the zone that hosts the ACU
                    supply_air_flow_rate = acu_simulation_results.air_mass_flow_rates[coil_model.uid.lower()]
                    # simulate the required chilled water mass flow rate of the cooling coil
                    if acu_simulation_results.acu_on_off_schedule[coil_model.uid.lower()] == 0:
                        water_mass_flow_rate = torch.tensor(0.0)
                        heat_transfer_rate = torch.tensor(0.0)
                    else:
                        supply_air_sp = acu_simulation_results.supply_air_sps[coil_model.uid.lower()]
                        inlet_air_temperature = acu_simulation_results.return_air_temperatures[coil_model.uid.lower()]
                        water_mass_flow_rate, heat_transfer_rate, supply_air_temperature = coil_model.solve(
                            T_air_in=inlet_air_temperature.view(-1, 1),
                            m_air=supply_air_flow_rate.view(-1, 1),
                            T_water_in=chw_sp.view(-1, 1),
                            T_air_out_sp=supply_air_sp.view(-1, 1)
                        )
                        total_demand_loop_m = total_demand_loop_m + water_mass_flow_rate
                    # record the cooling coil property
                    acu_simulation_results.sensible_heat_transfer_rate[coil_model.uid.lower()] = heat_transfer_rate
                    acu_simulation_results.water_mass_flow_rate[coil_model.uid.lower()] = water_mass_flow_rate
                    # simulate the return temperature of a cooling coil
                    if water_mass_flow_rate == 0.0:
                        return_temp = chw_sp
                    else:
                        return_temp = chw_sp + heat_transfer_rate / (
                                water_mass_flow_rate * water_specific_heat
                        )
                    branch_fluid_properties["demand"][demand_branch_name] = BranchData(
                        inlet_temperature=chw_sp,
                        inlet_mass_flow_rate=water_mass_flow_rate,
                        outlet_temperature=return_temp,
                        outlet_mass_flow_rate=water_mass_flow_rate,
                    )
                    # update the total demand-side mass flow rate and the weighted return temperature
                    weighted_return_temperature += return_temp * water_mass_flow_rate
                    num_middle_branches += 1
                    # the cooling load that should be met by the chiller plant is equal to IT power and CRAH power
                    total_cooling_load += (
                            heat_transfer_rate.view(-1) + acu_simulation_results.fan_powers[
                        coil_model.uid.lower()].view(-1)
                    )

            # calculate average return temperature
            average_return_temperature = chw_sp + total_cooling_load / (water_specific_heat * total_demand_loop_m)

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

            # supply-side simulation starts
            # determine supply-side available chillers at the current time step
            available_supply_branches = []
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if supply_branch["side"] == "middle":
                    if int(chiller_availability_schedule[supply_branch_name]) == 1:
                        available_supply_branches.append(supply_branch_name)
            num_available_chillers = len(available_supply_branches)
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
                    if supply_branch_name in available_supply_branches:
                        branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                            inlet_temperature=average_return_temperature,
                            inlet_mass_flow_rate=total_demand_loop_m / num_available_chillers,
                            outlet_temperature=chw_sp,
                            outlet_mass_flow_rate=total_demand_loop_m / num_available_chillers,
                        )
                    else:
                        branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                            inlet_temperature=average_return_temperature,
                            inlet_mass_flow_rate=0.0 * total_demand_loop_m,
                            outlet_temperature=average_return_temperature,
                            outlet_mass_flow_rate=0.0 * total_demand_loop_m,
                        )
                if supply_branch["side"] == "outlet":
                    branch_fluid_properties["supply"][supply_branch_name] = BranchData(
                        inlet_temperature=chw_sp,
                        inlet_mass_flow_rate=total_demand_loop_m,
                        outlet_temperature=chw_sp,
                        outlet_mass_flow_rate=total_demand_loop_m,
                    )

            # distribute cooling load to each chiller according to the uniform load workloads
            chiller_cooling_loads = {}
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if "chiller" in supply_branch.keys():
                    if supply_branch_name in available_supply_branches:
                        chiller_model = supply_branch["chiller"]
                        chiller_cooling_loads[chiller_model.uid] = total_cooling_load / num_available_chillers
                    else:
                        chiller_cooling_loads[supply_branch["chiller"].uid] = torch.tensor([[0.0]])

            # Equipment power consumption simulation of the chilled water loop
            for supply_branch_name, supply_branch in chilled_water_loop["supply_branches"].items():
                if "pump" in supply_branch.keys():
                    pump_model = supply_branch["pump"]
                    pump_power = pump_model(
                        branch_fluid_properties["supply"][supply_branch_name].inlet_M
                    )
                    chilled_water_pump_property[pump_model.uid] = Batch(
                        mass_flow_rate=branch_fluid_properties["supply"][supply_branch_name].inlet_M,
                        power=pump_power,
                    )
                if "chiller" in supply_branch.keys():
                    chiller_model = supply_branch["chiller"]
                    chiller_power = chiller_model(
                        cooling_load=chiller_cooling_loads[chiller_model.uid],
                        chw_sp=chw_sp,
                        cw_sp=plant_control_inputs[f"{chiller_model.uid} condenser water loop"]["supply_sp"],
                    )
                    chiller_property[chiller_model.uid] = Batch(
                        cooling_load=chiller_cooling_loads[chiller_model.uid],
                        power=chiller_power,
                        chilled_water_temperature=chw_sp,
                        condenser_water_temperature=plant_control_inputs[f"{chiller_model.uid} condenser water loop"][
                            "supply_sp"],
                    )

        return Batch(acu_property), Batch(chilled_water_pump_property), Batch(chiller_property)

    def collect(self, data: dict):
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        # feed online data to the chilled water loop equipment models
        for chw_loop_name, chw_loop_models in self.chw_loop_models.items():
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
        for chw_loop_name, chw_loop_models in self.chw_loop_models.items():
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
        states: Batch,
        actions: Batch,
        inputs: Batch,
        **kwargs,
    ) -> Batch:
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        acu_simulation_results, chilled_water_pump_property, chiller_property = self._sim(
            plant_control_inputs=plant_control_inputs,
            acu_simulation_results=acu_simulation_results
        )
        return Batch(
            acu_simulation_results=acu_simulation_results,
            chilled_water_pump_property=chilled_water_pump_property,
            chiller_property=chiller_property,
        )
