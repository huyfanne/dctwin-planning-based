from typing import Dict
from loguru import logger

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

from dctwin.utils.const import water_specific_heat, rho_water


class PlantManager(nn.Module):
    """
    PlantManager is used to manage the plant loops of the building. It contains the following attributes:
    :param device_key_mapping: the mapping between the device name and the device key
    :param zones: the zones of the building that are connected to the plant loops
    :param plant: the chiller plant object of the building
    """

    def __init__(
        self,
        device_key_mapping: Dict,
        zones: Dict[str, Room],
        plant: Plant,
        time_step: float = None
    ) -> None:

        super(PlantManager, self).__init__()

        self.zones = zones
        self.plant = plant
        self.device_key_mapping = device_key_mapping
        self.time_step = time_step

        # Initialize the models for the plant loops
        self._init_models()

    def _init_models(self) -> None:
        for loops in [
            self.plant.secondary_chilled_water_loops,
            self.plant.chilled_water_loops,
            self.plant.condenser_water_loops,
        ]:
            if loops is None:
                continue
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
                    key_mapping=self.device_key_mapping,
                    learnable=False  # TODO: add learnable cooling tower models
                )

        if branch_components.heat_exchangers:
            for component_id, component in branch_components.heat_exchangers.items():
                component.model = HeatExchanger(
                    config=component,
                    key_mapping=self.device_key_mapping,
                    internal_fluid_name="water",
                    external_fluid_name="air"
                )

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
        states_next: Batch,
        actions: Batch,
        external_inputs: Batch
    ):
        """
        Simulate the building with the learned models and the given control signals (acts)
        :return:
        """
        if self.plant.secondary_chilled_water_loops is not None:
            # Demand-side fluid property simulation of the chilled water loop
            total_demand_loop_m = 0.
            weighted_return_temperature = 0.
            total_cooling_load = 0.
            for loop_name, loop in self.plant.secondary_chilled_water_loops.items():
                # get the supply water temperature setpoint of the secondary chilled water loop
                middle_supply_branches = {
                    k: v for k, v in loop.supply_branches.items() if v.side == "middle"
                }
                supply_water_temperature = torch.zeros(1, 1)
                num_active_tanks = 0
                for branch_name, branch in middle_supply_branches.items():
                    if branch.components.tanks is not None:
                        tank_name = list(branch.components.tanks.keys())[0]
                        assert len(branch.components.tanks) == 1, \
                            logger.critical("Only one tank is allowed in one branch")
                        if actions[tank_name].on_off_schedule == 1:
                            supply_water_temperature += states.plants[tank_name].tank_water_temperature
                            num_active_tanks += 1
                    if branch.components.heat_exchangers is not None:
                        # TODO: if heat exchangers present, the supply water temperature is the setpoint temperature
                        pass
                supply_water_temperature /= num_active_tanks
                # get inlet, outlet and middle demand branches
                inlet_branches = {
                    k: v for k, v in loop.demand_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in loop.demand_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in loop.demand_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")
                branch_total_flow_rate = torch.zeros(1, 1)
                branch_heat_transfer_rate = torch.zeros(1, 1)
                branch_outlet_temperature = supply_water_temperature
                # simulate the middle branches
                for branch_name, branch in middle_branches.items():
                    assert len(branch.components.acu) == 1, logger.critical(
                        "Only one ACU is allowed in the middle branch"
                    )
                    acu_name = list(branch.components.acu.keys())[0]
                    acu = branch.components.acu[acu_name]
                    if actions[acu_name].on_off_schedule == 1:
                        water_mass_flow_rate, heat_transfer_rate, _ = acu.model.solve(
                            T_air_in=states_next.zones[acu_name].return_air_temperature.view(-1, 1),
                            m_air=states_next.zones[acu_name].supply_air_mass_flow_rate.view(-1, 1),
                            T_water_in=supply_water_temperature.view(-1, 1),
                            T_air_out_sp=actions[acu_name].supply_temperature_sp.view(-1, 1)
                        )
                        branch_total_flow_rate += water_mass_flow_rate
                        branch_heat_transfer_rate += (
                            heat_transfer_rate +
                            states_next.zones[acu_name].fan_power * acu.power.motor_in_airstream_fraction
                        )
                        branch_outlet_temperature = supply_water_temperature + heat_transfer_rate / (
                            water_mass_flow_rate * water_specific_heat
                        )
                    states_next.plants[branch_name].branch_inlet_temperature = supply_water_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = branch_total_flow_rate
                    states_next.plants[branch_name].branch_outlet_temperature = branch_outlet_temperature
                    weighted_return_temperature += branch_outlet_temperature * branch_total_flow_rate

                    total_demand_loop_m += branch_total_flow_rate
                    total_cooling_load += branch_heat_transfer_rate

                # calculate average return temperature
                average_return_temperature = supply_water_temperature + total_cooling_load / (
                    water_specific_heat * total_demand_loop_m
                )

                # fill in fluid properties for the inlet and outlet branches
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = supply_water_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = supply_water_temperature

                for branch_name, branch in outlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # supply-side fluid property simulation of the chilled water loop
                inlet_branches = {
                    k: v for k, v in loop.supply_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in loop.supply_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in loop.supply_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")

                # simulate the supply inlet branch
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # simulate the middle supply branches
                # step 1: distribute total mass flow rate into multiple branches
                for branch_name, branch in middle_branches.items():
                    # if tanks are present, update the tank temperature by simulating the tank thermal model
                    if branch.components.tanks is not None:
                        tank_name = list(branch.components.tanks.keys())[0]
                        tank_model = branch.components.tanks[tank_name].model
                        if actions[tank_name].on_off_schedule == 1:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = (
                                total_demand_loop_m / num_active_tanks
                            )
                            # TODO: Get T_source_in from primary chilled water loop setpoint
                            assert self.time_step is not None, logger.critical("Time step is set to None!")
                            tank_temperature = tank_model.forward(
                                T_tank_current=states.plants[tank_name].tank_water_temperature,
                                T_outdoor=external_inputs.outdoor_temperature,
                                T_use_in=average_return_temperature,
                                T_source_in=actions["chilled water loop"].supply_temperature_sp,
                                m_use=states_next.plants[branch_name].branch_water_mass_flow_rate,
                                m_source=actions[tank_name].use_side_mass_flow_rate,
                                time=torch.tensor(self.time_step, dtype=torch.float32, requires_grad=False),
                            )
                            states_next.plants[tank_name].tank_water_temperature = tank_temperature
                            states_next.plants[branch_name].branch_outlet_temperature = tank_temperature
                        else:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = torch.tensor(
                                [0.], dtype=torch.float32
                            )
                            states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                    # if heat exchangers are present, run the heat exchanger to cool down the return warm water
                    elif branch.components.heat_exchangers is not None:
                        # TODO: simulate the process of cooling down the return warm water from the demand side with HX
                        pass

                    else:
                        raise logger.critical(
                            "Only tanks and heat exchangers are allowed in the supply side of "
                            "the secondary chilled water loop"
                        )

                    # simulate the supply outlet branch
                    for branch_name, branch in outlet_branches.items():
                        states_next.plants[branch_name].branch_inlet_temperature = supply_water_temperature
                        states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                        states_next.plants[branch_name].branch_outlet_temperature = supply_water_temperature

                # Only passive devices are allowed in the supply-side of the secondary chilled water loop
                for branch_name, branch in loop.supply_branches.items():
                    if branch.components.pumps is not None:
                        assert len(branch.components.pumps) == 1, logger.critical(
                            "Only one pump is allowed for each supply branch"
                        )
                        pump_name = list(branch.components.pumps.keys())[0]
                        pump_model = branch.components.pumps[pump_name].model
                        states_next.plants[pump_name].power = pump_model(
                            states_next.plants[branch_name].branch_water_mass_flow_rate,
                        )

        if self.plant.chilled_water_loops is not None:
            # Demand-side fluid property simulation of the chilled water loop
            total_demand_loop_m = 0.
            weighted_return_temperature = 0.
            total_cooling_load = 0.
            for chilled_water_loop_name, chilled_water_loop in self.plant.chilled_water_loops.items():
                # get the setpoint of the chilled water loop
                chw_sp = actions[chilled_water_loop_name].supply_temperature_sp
                inlet_branches = {
                    k: v for k, v in chilled_water_loop.demand_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in chilled_water_loop.demand_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in chilled_water_loop.demand_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")
                branch_total_flow_rate = torch.zeros(1, 1)
                branch_heat_transfer_rate = torch.zeros(1, 1)
                branch_outlet_temperature = chw_sp.view(1, 1)
                # simulate the middle branches
                for branch_name, branch in middle_branches.items():
                    # handle the case when the demand branch contains a cooling coil of a ACU
                    if branch.components.acu is not None:
                        assert len(branch.components.acu) == 1, logger.critical(
                            "Only one ACU is allowed in the middle branch"
                        )
                        acu_name = list(branch.components.acu.keys())[0]
                        acu = branch.components.acu[acu_name]
                        if actions[acu_name].on_off_schedule == 1:
                            water_mass_flow_rate, heat_transfer_rate, _ = acu.model.solve(
                                T_air_in=states_next.zones[acu_name].return_air_temperature.view(-1, 1),
                                m_air=states_next.zones[acu_name].supply_air_mass_flow_rate.view(-1, 1),
                                T_water_in=chw_sp.view(-1, 1),
                                T_air_out_sp=actions[acu_name].supply_temperature_sp.view(-1, 1)
                            )
                            branch_total_flow_rate = water_mass_flow_rate
                            branch_heat_transfer_rate = (
                                heat_transfer_rate +
                                states_next.zones[acu_name].fan_power * acu.power.motor_in_airstream_fraction
                            )
                            branch_outlet_temperature = chw_sp + heat_transfer_rate / (
                                water_mass_flow_rate * water_specific_heat
                            )
                        states_next.plants[branch_name].branch_inlet_temperature = chw_sp
                        states_next.plants[branch_name].branch_water_mass_flow_rate = branch_total_flow_rate
                        states_next.plants[branch_name].branch_outlet_temperature = branch_outlet_temperature
                        weighted_return_temperature += branch_outlet_temperature * branch_total_flow_rate

                        total_demand_loop_m += branch_total_flow_rate
                        total_cooling_load += branch_heat_transfer_rate

                    # handle the case when the demand branch contains a tank
                    elif branch.components.tanks is not None:
                        assert len(branch.components.tanks) == 1, \
                            logger.critical("Only one tank is allowed in one branch")
                        tank_name = list(branch.components.tanks.keys())[0]
                        if actions[tank_name].on_off_schedule == 1:
                            branch_total_flow_rate = actions[tank_name].use_side_mass_flow_rate
                            # required cooling load to cool down the thermal storage tank
                            branch_heat_transfer_rate = water_specific_heat * branch_total_flow_rate * (
                                states_next.plants[tank_name].tank_water_temperature - chw_sp
                            )
                            # update the tank temperature
                            states_next.plants[branch_name].branch_inlet_temperature = chw_sp
                            states_next.plants[branch_name].branch_water_mass_flow_rate = branch_total_flow_rate
                            states_next.plants[branch_name].branch_outlet_temperature = (
                                states_next.plants[tank_name].tank_water_temperature
                            )
                            weighted_return_temperature += (
                                states_next.plants[branch_name].branch_outlet_temperature * branch_total_flow_rate
                            )
                            total_demand_loop_m += branch_total_flow_rate
                            total_cooling_load += branch_heat_transfer_rate
                    # handle the case when the demand branch contains a heat exchanger
                    elif branch.components.heat_exchangers is not None:
                        assert len(branch.components.heat_exchangers) == 1, \
                            logger.critical("Only one heat exchanger is allowed in one branch")
                        heat_exchanger_name = list(branch.components.heat_exchangers.keys())[0]
                        heat_exchanger = branch.components.heat_exchangers[heat_exchanger_name]
                        if actions[heat_exchanger_name].on_off_schedule == 1:
                            # TODO: simulate the demand side of the heat exchanger
                            pass
                    else:
                        raise logger.critical(
                            "Only ACUs, tanks and heat exchangers are allowed in the demand side"
                            " of the primary chilled water loop"
                        )

                # calculate average return temperature
                average_return_temperature = chw_sp + total_cooling_load / (
                    water_specific_heat * total_demand_loop_m
                )

                # fill in fluid properties for the inlet and outlet branches
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = chw_sp
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = chw_sp

                for branch_name, branch in outlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # supply-side fluid property simulation of the chilled water loop
                inlet_branches = {
                    k: v for k, v in chilled_water_loop.supply_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in chilled_water_loop.supply_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in chilled_water_loop.supply_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")

                # simulate the supply inlet branch
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # simulate the middle supply branches

                # step 1: get the active chillers
                num_active_chillers = 0
                for branch_name, branch in middle_branches.items():
                    if branch.components.chillers is not None:
                        assert len(branch.components.chillers) == 1,\
                            logger.critical("Only one chiller is allowed for each middle supply branch")
                        chiller_name = list(branch.components.chillers.keys())[0]
                        if actions[chiller_name].on_off_schedule == 1:
                            num_active_chillers += 1

                # step 2: distribute total mass flow rate into multiple branches
                for branch_name, branch in middle_branches.items():
                    if branch.components.chillers is not None:
                        chiller_name = list(branch.components.chillers.keys())[0]
                        if actions[chiller_name].on_off_schedule == 1:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = (
                                total_demand_loop_m / num_active_chillers
                            )
                            states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature
                        else:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = torch.tensor(
                                [0.], dtype=torch.float32
                            )
                            states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # simulate the supply outlet branch
                for branch_name, branch in outlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = chw_sp
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = chw_sp

                # Device performance simulation
                for branch_name, branch in chilled_water_loop.supply_branches.items():
                    if branch.components.pumps is not None:
                        assert len(branch.components.pumps) == 1, logger.critical(
                            "Only one pump is allowed for each supply branch"
                        )
                        pump_name = list(branch.components.pumps.keys())[0]
                        pump_model = branch.components.pumps[pump_name].model
                        states_next.plants[pump_name].power = pump_model(
                            states_next.plants[branch_name].branch_water_mass_flow_rate,
                        )

                    if branch.components.chillers is not None:
                        assert len(branch.components.chillers) == 1, logger.critical(
                            "Only one chiller is allowed for each supply branch"
                        )
                        chiller_name = list(branch.components.chillers.keys())[0]
                        chiller_model = branch.components.chillers[chiller_name].model
                        if num_active_chillers > 0:
                            states_next.plants[chiller_name].cooling_load = total_cooling_load / num_active_chillers
                        else:
                            states_next.plants[chiller_name].cooling_load = torch.zeros(1)
                        states_next.plants[chiller_name].power = chiller_model(
                            cooling_load=states_next.plants[chiller_name].cooling_load,
                            chw_sp=chw_sp,
                            cw_sp=external_inputs.outdoor_temperature
                        )

                    if branch.components.pipes is not None:
                        pass

        if self.plant.condenser_water_loops is not None:
            # Demand-side fluid property simulation of the chilled water loop
            total_demand_loop_m = 0.
            weighted_return_temperature = 0.
            total_cooling_load = 0.
            for condenser_water_loop_name, condenser_water_loop in self.plant.condenser_water_loops.items():
                # get the setpoint of the chilled water loop
                cw_sp = external_inputs.outdoor_temperature
                inlet_branches = {
                    k: v for k, v in condenser_water_loop.demand_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in condenser_water_loop.demand_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in condenser_water_loop.demand_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")
                branch_total_flow_rate = torch.zeros(1, 1)
                branch_heat_transfer_rate = torch.zeros(1, 1)
                branch_outlet_temperature = cw_sp.view(1, 1)
                # simulate the middle branches
                for branch_name, branch in middle_branches.items():
                    assert len(branch.components.chillers) == 1, \
                        logger.critical("Only one chiller is allowed in the middle branch")
                    chiller_name = list(branch.components.chillers.keys())[0]
                    chiller = branch.components.chillers[chiller_name]
                    if actions[chiller_name].on_off_schedule == 1:
                        water_mass_flow_rate = chiller.cooling.reference_condenser_fluid_flow_rate * rho_water
                        heat_transfer_rate = states_next.plants[chiller_name].cooling_load
                        branch_total_flow_rate += water_mass_flow_rate
                        branch_heat_transfer_rate += states_next.plants[chiller_name].cooling_load
                        branch_outlet_temperature = cw_sp + heat_transfer_rate / (
                            water_mass_flow_rate * water_specific_heat
                        )
                    states_next.plants[branch_name].branch_inlet_temperature = cw_sp
                    states_next.plants[branch_name].branch_water_mass_flow_rate = branch_total_flow_rate
                    states_next.plants[branch_name].branch_outlet_temperature = branch_outlet_temperature
                    weighted_return_temperature += branch_outlet_temperature * branch_total_flow_rate

                    total_demand_loop_m += branch_total_flow_rate
                    total_cooling_load += branch_heat_transfer_rate

                # calculate average return temperature
                average_return_temperature = cw_sp + total_cooling_load / (water_specific_heat * total_demand_loop_m)

                # fill in fluid properties for the inlet and outlet branches
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = cw_sp
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = cw_sp

                for branch_name, branch in outlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # supply-side fluid property simulation of the chilled water loop
                inlet_branches = {
                    k: v for k, v in condenser_water_loop.supply_branches.items() if v.side == "inlet"
                }
                assert len(inlet_branches) == 1, logger.critical("Only one inlet branch is allowed")
                middle_branches = {
                    k: v for k, v in condenser_water_loop.supply_branches.items() if v.side == "middle"
                }
                outlet_branches = {
                    k: v for k, v in condenser_water_loop.supply_branches.items() if v.side == "outlet"
                }
                assert len(outlet_branches) == 1, logger.critical("Only one outlet branch is allowed")

                # simulate the supply inlet branch
                for branch_name, branch in inlet_branches.items():
                    states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                    states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                    states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # simulate the middle supply branches
                # step 1: get the active chillers
                num_active_cooling_towers = 0
                for branch_name, branch in middle_branches.items():
                    if branch.components.cooling_towers is not None:
                        assert len(branch.components.cooling_towers) == 1, \
                            logger.critical("Only one cooling tower is allowed for each middle supply branch")
                        cooling_tower_name = list(branch.components.cooling_towers.keys())[0]
                        if actions[cooling_tower_name].on_off_schedule == 1:
                            num_active_cooling_towers += 1
                # step 2: distribute total mass flow rate into multiple branches
                for branch_name, branch in middle_branches.items():
                    if branch.components.cooling_towers is not None:
                        cooling_tower_name = list(branch.components.cooling_towers.keys())[0]
                        if actions[cooling_tower_name].on_off_schedule == 1:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = (
                                total_demand_loop_m / num_active_cooling_towers
                            )
                            states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature
                        else:
                            states_next.plants[branch_name].branch_inlet_temperature = average_return_temperature
                            states_next.plants[branch_name].branch_water_mass_flow_rate = torch.tensor(
                                [0.], dtype=torch.float32
                            )
                            states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                    # simulate the supply outlet branch
                    for branch_name, branch in outlet_branches.items():
                        states_next.plants[branch_name].branch_inlet_temperature = cw_sp
                        states_next.plants[branch_name].branch_water_mass_flow_rate = total_demand_loop_m
                        states_next.plants[branch_name].branch_outlet_temperature = average_return_temperature

                # device performance simulation
                for branch_name, branch in condenser_water_loop.supply_branches.items():
                    if branch.components.pumps is not None:
                        assert len(branch.components.pumps) == 1, logger.critical(
                            "Only one pump is allowed for each supply branch"
                        )
                        pump_name = list(branch.components.pumps.keys())[0]
                        pump_model = branch.components.pumps[pump_name].model
                        states_next.plants[pump_name].power = pump_model(
                            states_next.plants[branch_name].branch_water_mass_flow_rate,
                        )
                    if branch.components.cooling_towers is not None:
                        assert len(branch.components.cooling_towers) == 1, logger.critical(
                            "Only one cooling tower is allowed for each supply branch"
                        )
                        cooling_tower_name = list(branch.components.cooling_towers.keys())[0]
                        cooling_tower_model = branch.components.cooling_towers[cooling_tower_name].model
                        states_next.plants[cooling_tower_name].cooling_load = (
                            total_cooling_load / num_active_cooling_towers
                        )
                        states_next.plants[cooling_tower_name].power = cooling_tower_model(
                            cw_return_water_temperature=states_next.plants[branch_name].branch_inlet_temperature,
                            cw_return_water_mass_flow_rate=states_next.plants[branch_name].branch_water_mass_flow_rate,
                            cw_supply_water_temperature=cw_sp,
                            outside_air_wetbulb_temperature=external_inputs.outdoor_temperature
                        )
