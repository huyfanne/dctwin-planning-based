from typing import Dict, Tuple

from dclib.cooling.plant.loops import ChilledWaterLoops, CondenserWaterLoops, SecondaryChilledWaterLoops, Branch
from loguru import logger

import torch
import torch.nn as nn

from dclib.building import Plant

from dclib.cooling.plant.facilities import Components

from dctwin.data.batch import Batch
from dctwin.models.cooling.facilities import (
    HeatExchanger,
    ChillerModel,
    PumpModel,
    ThermalStorageTankModel,
    CoolingTowerModel,
)

from dctwin.utils.const import water_specific_heat


class PlantManager(nn.Module):
    """
    PlantManager is used to manage the plant loops of the building. It contains the following attributes:
    :param plant: the plant object that contains the plant loops
    :param device_key_mapping: the mapping between the device name and the device key
    :param time_step: the time step of the simulation
    """
    def __init__(
        self,
        plant: Plant,
        device_key_mapping: Dict,
        time_step: float = None,
    ) -> None:
        super(PlantManager, self).__init__()
        self.plant = plant
        self.device_key_mapping = device_key_mapping
        self.time_step = time_step
        # Initialize the models for the plant loops
        self._init_models()

    def _init_models(self) -> None:
        """
        Initialize the models for the plant loops
        """
        _component_models = {}
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
                    _component_models = self._init_facility_models(
                        branch_components=branch.components,
                        component_models=_component_models,
                    )
                # half-loop supply side components
                for branch_id, branch in loop.supply_branches.items():
                    _component_models = self._init_facility_models(
                        branch_components=branch.components,
                        component_models=_component_models,
                    )

    def _init_facility_models(
        self,
        branch_components: Components,
        component_models: Dict,
    ) -> Dict:
        """
        Initialize the models for the plant components,
        including pipes, pumps, chillers, tanks, cooling towers, etc.
        """
        if branch_components.pipes:
            for component_id, component in branch_components.pipes.items():
                if component_id not in component_models.keys():
                    component.model = None
                    component_models[component_id] = component.model
                    self.add_module(component_id, component.model)
                else:
                    component.model = component_models[component_id]

        if branch_components.pumps:
            for component_id, component in branch_components.pumps.items():
                if component_id not in component_models.keys():
                    component.model = PumpModel(
                        config=component,
                        key_mapping=self.device_key_mapping
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        if branch_components.acu:
            for component_id, component in branch_components.acu.items():
                if component_id not in component_models.keys():
                    component.model = HeatExchanger(
                        config=component,
                        key_mapping=self.device_key_mapping,
                        internal_fluid_name="water",
                        external_fluid_name="air"
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        if branch_components.chillers:
            for component_id, component in branch_components.chillers.items():
                if component_id not in component_models.keys():
                    component.model = ChillerModel(
                        config=component,
                        key_mapping=self.device_key_mapping,
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        if branch_components.tanks:
            for component_id, component in branch_components.tanks.items():
                if component_id not in component_models.keys():
                    component.model = ThermalStorageTankModel(
                        config=component,
                        key_mapping=self.device_key_mapping,
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        if branch_components.cooling_towers:
            for component_id, component in branch_components.cooling_towers.items():
                if component_id not in component_models.keys():
                    component.model = CoolingTowerModel(
                        config=component,
                        key_mapping=self.device_key_mapping,
                        learnable=False  # TODO: add learnable cooling tower models
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        if branch_components.heat_exchangers:
            for component_id, component in branch_components.heat_exchangers.items():
                if component_id not in component_models.keys():
                    component.model = HeatExchanger(
                        config=component,
                        key_mapping=self.device_key_mapping,
                        internal_fluid_name="water",
                        external_fluid_name="air",
                    )
                    self.add_module(component_id, component.model)
                    component_models[component_id] = component.model
                else:
                    component.model = component_models[component_id]

        return component_models

    @staticmethod
    def _determine_actual_mass_flow_rate(
        data: Batch,
        branch: Branch,
        requested_mass_flow_rate: torch.Tensor,
    ) -> torch.Tensor:
        """
        Determine the actual mass flow rate based on the requested mass flow rate and the pump on/off schedule
        The actual mass flow rate is the minimum of the requested mass flow rate and the maximum mass flow rate of the pump
        :param data: the data batch
        :param branch: the branch object
        :param requested_mass_flow_rate: the requested mass flow rate
        """
        actual_mass_flow_rate = requested_mass_flow_rate
        if branch.components.pumps is not None:
            for component_id, component in branch.components.pumps.items():
                if len(branch.components.pumps) > 1:
                    raise logger.critical("Only one pump is allowed in the middle branch")
                if data.acts[component_id].on_off_schedule == 1:
                    maximum_mass_flow_rate = torch.tensor(
                        [component.cooling.design_maximum_flow_rate * 1000],
                        dtype=torch.float32,
                        requires_grad=True,
                    )
                    actual_mass_flow_rate = torch.min(requested_mass_flow_rate, maximum_mass_flow_rate)
                else:
                    actual_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
        return actual_mass_flow_rate

    @staticmethod
    def _set_branch_inlet_properties(
        data: Batch,
        current_branch: Dict[str, Branch],
        last_branch: Dict[str, Branch],
        loop_id: str,
        loop_side: str,
    ) -> None:
        """
        Set the branch inlet water temperature
        """
        last_branch_id = list(last_branch.keys())[0]
        current_branch_id = list(current_branch.keys())[0]
        if len(data.acts[loop_id].supply_temperature_sp) != 0 and loop_side == "demand":
            # set the outlet branch water temperature to the loop supply temperature setpoint
            data.obs_next.plants[last_branch_id].outlet_temperature = data.acts[loop_id].supply_temperature_sp
            data.obs_next.plants[current_branch_id].inlet_temperature = (
                data.obs_next.plants[last_branch_id].outlet_temperature
            )
        else:
            # set the outlet branch water temperature to the inlet water temperature if the setpoint is not provided
            if loop_side == "demand":
                data.obs_next.plants[last_branch_id].outlet_temperature =\
                    data.obs.plants[last_branch_id].inlet_temperature
                data.obs_next.plants[current_branch_id].inlet_temperature = (
                    data.obs_next.plants[last_branch_id].outlet_temperature
                )
            elif loop_side == "supply":
                data.obs_next.plants[current_branch_id].inlet_temperature = (
                    data.obs_next.plants[last_branch_id].outlet_temperature
                )
            else:
                raise logger.critical(f"Loop side should be either demand or supply, not {loop_side}")

    @staticmethod
    def _reset_demand_side_data(data: Batch, loop_id: str) -> None:
        data.obs_next.plants[loop_id].demand_side_total_cooling_load =\
            torch.tensor([0.], dtype=torch.float32)
        data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate =\
            torch.tensor([0.], dtype=torch.float32)

    @staticmethod
    def _set_main_branch_mass_flow_rate(
        data: Batch,
        loop_id: str,
        supply_branches: Dict,
        demand_branches: Dict,
    ) -> None:
        supply_inlet_branch = {
            k: v for k, v in supply_branches.items() if v.side == "inlet"
        }
        inlet_branch_id = list(supply_inlet_branch.keys())[0]
        data.obs_next.plants[inlet_branch_id].water_mass_flow_rate = (
            data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate
        )
        supply_outlet_branch = {
            k: v for k, v in supply_branches.items() if v.side == "outlet"
        }
        outlet_branch_id = list(supply_outlet_branch.keys())[0]
        data.obs_next.plants[outlet_branch_id].water_mass_flow_rate = (
            data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate
        )
        demand_inlet_branch = {
            k: v for k, v in demand_branches.items() if v.side == "inlet"
        }
        inlet_branch_id = list(demand_inlet_branch.keys())[0]
        data.obs_next.plants[inlet_branch_id].water_mass_flow_rate = (
            data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate
        )
        demand_outlet_branch = {
            k: v for k, v in demand_branches.items() if v.side == "outlet"
        }
        outlet_branch_id = list(demand_outlet_branch.keys())[0]
        data.obs_next.plants[outlet_branch_id].water_mass_flow_rate = (
            data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate
        )

    @staticmethod
    def _update_spliter(data: Batch, split_branch_id: str, inlet_branch: Dict) -> None:
        inlet_branch_id = list(inlet_branch.keys())[0]
        data.obs_next.plants[split_branch_id].inlet_temperature = (
            data.obs_next.plants[inlet_branch_id].outlet_temperature
        )

    @staticmethod
    def _update_mixer(data: Batch, outlet_branch_id: str, mixed_branches: Dict) -> None:
        mixed_outlet_temperature, mixed_outlet_water_mass_flow_rate = torch.zeros(1), torch.zeros(1)
        for branch_id, branch in mixed_branches.items():
            mixed_outlet_water_mass_flow_rate += data.obs_next.plants[branch_id].water_mass_flow_rate
        for branch_id, branch in mixed_branches.items():
            flow_rate_frac = data.obs_next.plants[branch_id].water_mass_flow_rate / mixed_outlet_water_mass_flow_rate
            mixed_outlet_temperature += data.obs_next.plants[branch_id].outlet_temperature * flow_rate_frac
        data.obs_next.plants[outlet_branch_id].inlet_temperature = mixed_outlet_temperature
        data.obs_next.plants[outlet_branch_id].water_mass_flow_rate = mixed_outlet_water_mass_flow_rate
        data.obs_next.plants[outlet_branch_id].outlet_temperature = mixed_outlet_temperature

    @staticmethod
    def _get_branches(branches: Dict) -> Tuple[Dict, Dict, Dict]:
        inlet_branch = {
            k: v for k, v in branches.items() if v.side == "inlet"
        }
        assert len(inlet_branch) == 1, logger.critical("Only one inlet branch is allowed")
        middle_branches = {
            k: v for k, v in branches.items() if v.side == "middle"
        }
        outlet_branch = {
            k: v for k, v in branches.items() if v.side == "outlet"
        }
        assert len(outlet_branch) == 1, logger.critical("Only one outlet branch is allowed")
        return inlet_branch, middle_branches, outlet_branch

    def _do_flow_and_load_distribution(
        self,
        data: Batch,
        loop_id: str,
        loop: SecondaryChilledWaterLoops | ChilledWaterLoops | CondenserWaterLoops,
        middle_branches: Dict,
    ) -> None:
        """
        Distribute the total demand cooling load and mass flow rate to the middle branches
        Currently, this method only supports UniformLoad and SequentialLoad distribution schemes
        :param data: the data batch
        :param loop_id: the loop id
        :param loop: the loop object
        :param middle_branches: the middle branches
        :return: None
        """
        total_cooling_load = data.obs_next.plants[loop_id].demand_side_total_cooling_load
        total_mass_flow_rate = data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate
        active_devices = []
        # determine the active devices list
        for branch_id, branch in middle_branches.items():
            if branch.components.chillers is not None:
                for component_id, component in branch.components.chillers.items():
                    if data.acts[component_id].on_off_schedule == 1:
                        active_devices.append(component_id)
                    else:
                        data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
            if branch.components.tanks is not None:
                for component_id, component in branch.components.tanks.items():
                    if data.acts[component_id].on_off_schedule == 1:
                        active_devices.append(component_id)
                    else:
                        data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
            if branch.components.cooling_towers is not None:
                for component_id, component in branch.components.cooling_towers.items():
                    if data.acts[component_id].on_off_schedule == 1:
                        active_devices.append(component_id)
                    else:
                        data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
            if branch.components.pumps is not None:
                for component_id, component in branch.components.pumps.items():
                    if data.acts[component_id].on_off_schedule == 1:
                        active_devices.append(component_id)
                    else:
                        data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
        # TODO: Add the rest of the components

        # perform load and mass flow distribution to each active device
        for branch_id, branch in middle_branches.items():
            if branch.components.chillers is not None:
                for component_id, component in branch.components.chillers.items():
                    if len(branch.components.chillers) > 1:
                        raise logger.critical("Only one chiller is allowed in the middle branch")
                    if component_id in active_devices:
                        if loop.meta.load_distribution_scheme == "UniformLoad":
                            total_mass_flow_rate_per_device = total_mass_flow_rate / len(active_devices)
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate_per_device
                            data.obs_next.plants[component_id].cooling_load = total_cooling_load / len(active_devices)
                        elif loop.meta.load_distribution_scheme == "SequentialLoad":
                            distributed_load = torch.min(
                                component.cooling.nominal_cooling_capacity,
                                total_cooling_load,
                            )
                            load_frac = distributed_load / total_cooling_load
                            remaining_cooling_load = total_cooling_load - distributed_load
                            remaining_cooling_load = torch.max(remaining_cooling_load, torch.tensor([0.]))
                            total_cooling_load = remaining_cooling_load
                            data.obs_next.plants[component_id].cooling_load = distributed_load
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate * load_frac
                        else:
                            raise logger.critical(
                                f"Invalid load distribution scheme: {loop.meta.load_distribution_scheme}"
                            )
            if branch.components.tanks is not None:
                for component_id, component in branch.components.tanks.items():
                    if len(branch.components.tanks) > 1:
                        raise logger.critical("Only one tank is allowed in the middle branch")
                    if component_id in active_devices:
                        if loop.meta.load_distribution_scheme == "UniformLoad":
                            total_mass_flow_rate_per_device = total_mass_flow_rate / len(active_devices)
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate_per_device
                            data.obs_next.plants[component_id].use_side_cooling_load \
                                = total_cooling_load / len(active_devices)
                        elif loop.meta.load_distribution_scheme == "SequentialLoad":
                            distributed_load = torch.min(
                                component.cooling.reference_capacity,
                                total_cooling_load,
                            )
                            load_frac = distributed_load / total_cooling_load
                            remaining_cooling_load = total_cooling_load - distributed_load
                            remaining_cooling_load = torch.max(remaining_cooling_load, torch.tensor([0.]))
                            total_cooling_load = remaining_cooling_load
                            data.obs_next.plants[component_id].cooling_load = distributed_load
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate * load_frac
                        else:
                            raise logger.critical(
                                f"Invalid load distribution scheme: {loop.meta.load_distribution_scheme}"
                            )
            if branch.components.cooling_towers is not None:
                for component_id, component in branch.components.cooling_towers.items():
                    if len(branch.components.cooling_towers) > 1:
                        raise logger.critical("Only one cooling tower is allowed in the middle branch")
                    if component_id in active_devices:
                        if loop.meta.load_distribution_scheme == "UniformLoad":
                            total_mass_flow_rate_per_device = total_mass_flow_rate / len(active_devices)
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate_per_device
                            data.obs_next.plants[component_id].cooling_load = total_cooling_load / len(active_devices)
                        elif loop.meta.load_distribution_scheme == "SequentialLoad":
                            distributed_load = torch.min(
                                # TODO: check the cooling capacity of the cooling tower
                                component.cooling.reference_capacity,
                                total_cooling_load,
                            )
                            load_frac = distributed_load / total_cooling_load
                            remaining_cooling_load = total_cooling_load - distributed_load
                            remaining_cooling_load = torch.max(remaining_cooling_load, torch.tensor([0.]))
                            total_cooling_load = remaining_cooling_load
                            data.obs_next.plants[component_id].cooling_load = distributed_load
                            data.obs_next.plants[branch_id].water_mass_flow_rate = total_mass_flow_rate * load_frac
                        else:
                            raise logger.critical(
                                f"Invalid load distribution scheme: {loop.meta.load_distribution_scheme}"
                            )

            actual_flow_rate = self._determine_actual_mass_flow_rate(
                data=data,
                branch=branch,
                requested_mass_flow_rate=data.obs_next.plants[branch_id].water_mass_flow_rate,
            )
            data.obs_next.plants[branch_id].water_mass_flow_rate = actual_flow_rate

    def _solve_branch_components(
        self,
        data: Batch,
        loop_id: str,
        loop_side: str,
        branch_id: str,
        branch: Branch,
    ) -> None:
        """
        Solve the branch component models to update the plant loop properties
        """

        if branch.components.pipes is not None:
            outlet_temperature = torch.zeros(1,)
            for component_id, component in branch.components.pipes.items():
                # TODO: add the pipe model
                temperature = data.obs_next.plants[branch_id].inlet_temperature
                outlet_temperature += temperature
            outlet_temperature = outlet_temperature / len(branch.components.pipes)
            data.obs_next.plants[branch_id].outlet_temperature = outlet_temperature

        if branch.components.acu is not None:
            for component_id, component in branch.components.acu.items():
                if len(branch.components.acu) > 1:
                    raise logger.critical("Only one ACU is allowed in the middle branch")
                if data.acts[component_id].on_off_schedule == 1:
                    coil_requested_mass_flow_rate, coil_heat_transfer_rate, _ = component.model.solve(
                        T_air_in=data.obs_next.zones[component_id].return_air_temperature,
                        m_air=data.obs_next.zones[component_id].supply_air_mass_flow_rate,
                        T_water_in=data.obs_next.plants[branch_id].inlet_temperature,
                        T_air_out_sp=data.acts[component_id].supply_temperature_sp,
                    )
                    coil_sensible_heat_load = (
                        coil_heat_transfer_rate +
                        data.obs_next.zones[component_id].fan_power *
                        component.power.motor_in_airstream_fraction
                    )
                    outlet_temperature = (
                        data.obs_next.plants[branch_id].inlet_temperature +
                        coil_heat_transfer_rate / (coil_requested_mass_flow_rate * water_specific_heat)
                    )
                    # update data
                    data.obs_next.plants[loop_id].demand_side_total_cooling_load += coil_sensible_heat_load
                    data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate += coil_requested_mass_flow_rate
                    data.obs_next.plants[branch_id].outlet_temperature = outlet_temperature
                    data.obs_next.plants[branch_id].water_mass_flow_rate = coil_requested_mass_flow_rate
                    data.obs_next.zones[component_id].coil_sensible_heat_load = coil_sensible_heat_load
                else:
                    # if the ACU is off, the mass flow rate is 0
                    data.obs_next.plants[branch_id].outlet_temperature = data.obs_next.plants[branch_id].inlet_temperature
                    data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)

        if branch.components.pumps is not None:
            for component_id, component in branch.components.pumps.items():
                if len(branch.components.pumps) > 1:
                    raise logger.critical("Cascade pumps are not supported")
                if data.acts[component_id].on_off_schedule == 1:
                    actual_flow_rate = self._determine_actual_mass_flow_rate(
                        data=data,
                        branch=branch,
                        requested_mass_flow_rate=data.obs_next.plants[branch_id].water_mass_flow_rate,
                    )
                    data.obs_next.plants[branch_id].water_mass_flow_rate = actual_flow_rate
                    # TODO: Add pump on/off schedule
                    pump_power = component.model.forward(
                        mass_flow_rate=data.obs_next.plants[branch_id].water_mass_flow_rate,
                    )
                    data.obs_next.plants[component_id].power = pump_power
                    data.obs_next.dc.total_facility_power += pump_power
                    data.obs_next.dc.total_dc_power += pump_power
                else:
                    data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)

        if branch.components.tanks is not None:
            for component_id, component in branch.components.tanks.items():
                # if len(branch.components.tanks) > 1:
                #     raise logger.critical("Only one tank is allowed in one branch")
                if data.acts[component_id].on_off_schedule == 1:
                    requested_flow_rate = data.acts[component_id].source_side_mass_flow_rate
                    actual_flow_rate = self._determine_actual_mass_flow_rate(
                        data=data,
                        branch=branch,
                        requested_mass_flow_rate=requested_flow_rate,
                    )
                    if loop_side == "supply":
                        tank_temperature, requested_cooling_load, supply_cooling_load = component.model.forward(
                            T_tank_current=data.obs.plants[component_id].tank_water_temperature,
                            T_outdoor=data.inps.outdoor_temperature,
                            T_use_in=data.obs_next.plants[branch_id].inlet_temperature,
                            T_source_in=data.acts[component.other_loop_side].supply_temperature_sp,
                            m_use=data.obs_next.plants[branch_id].water_mass_flow_rate,
                            m_source=actual_flow_rate,
                            time=torch.tensor(self.time_step, dtype=torch.float32, requires_grad=False),
                        )
                        data.obs_next.plants[branch_id].outlet_temperature = tank_temperature
                        data.obs_next.plants[component_id].tank_water_temperature = tank_temperature
                        data.obs_next.plants[component_id].source_side_cooling_load = requested_cooling_load
                        data.obs_next.plants[component_id].source_side_mass_flow_rate = actual_flow_rate
                        data.obs_next.plants[component_id].use_side_mass_flow_rate = (
                            data.obs_next.plants[branch_id].water_mass_flow_rate
                        )
                    elif loop_side == "demand":
                        data.obs_next.plants[loop_id].demand_side_total_cooling_load += (
                            data.obs_next.plants[component_id].source_side_cooling_load
                        )
                        data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate += (
                            data.obs_next.plants[component_id].source_side_mass_flow_rate
                        )
                        data.obs_next.plants[branch_id].outlet_temperature = (
                            data.obs_next.plants[component_id].tank_water_temperature
                        )
                        data.obs_next.plants[branch_id].water_mass_flow_rate = (
                            data.obs_next.plants[component_id].source_side_mass_flow_rate
                        )
                    else:
                        raise logger.critical(f"Loop side should be either demand or supply, not {loop_side}")
                else:
                    data.obs_next.plants[branch_id].outlet_temperature =\
                        data.obs_next.plants[branch_id].inlet_temperature
                    data.obs_next.plants[branch_id].water_mass_flow_rate =\
                        torch.tensor([0.], dtype=torch.float32)

        if branch.components.chillers is not None:
            for component_id, component in branch.components.chillers.items():
                if data.acts[component_id].on_off_schedule == 1:
                    if loop_side == "supply":
                        cw_sp = data.acts[component.other_loop_side].supply_temperature_sp \
                            if data.acts[component.other_loop_side].supply_temperature_sp \
                            else data.inps.outdoor_temperature
                        chiller_power = component.model.forward(
                            cooling_load=data.obs_next.plants[component_id].cooling_load,
                            chw_sp=data.acts[loop_id].supply_temperature_sp,  # All chillers share the same sp
                            cw_sp=cw_sp,
                        )
                        data.obs_next.plants[branch_id].outlet_temperature = data.acts[loop_id].supply_temperature_sp
                        data.obs_next.plants[component_id].power = chiller_power
                        data.obs_next.dc.total_facility_power += chiller_power
                        data.obs_next.dc.total_dc_power += chiller_power
                    elif loop_side == "demand":
                        requested_flow_rate = torch.tensor(
                            [component.cooling.reference_condenser_fluid_flow_rate * 1000.], dtype=torch.float32
                        )
                        actual_flow_rate = self._determine_actual_mass_flow_rate(
                            data=data,
                            branch=branch,
                            requested_mass_flow_rate=requested_flow_rate,
                        )
                        data.obs_next.plants[loop_id].demand_side_total_cooling_load += (
                            data.obs_next.plants[component_id].cooling_load
                        )
                        data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate += actual_flow_rate
                        data.obs_next.plants[branch_id].water_mass_flow_rate = actual_flow_rate
                        data.obs_next.plants[branch_id].outlet_temperature = (
                            data.obs_next.plants[branch_id].inlet_temperature +
                            data.obs_next.plants[component_id].cooling_load /
                            (data.obs_next.plants[branch_id].water_mass_flow_rate * water_specific_heat)
                        )
                    else:
                        raise logger.critical(f"Loop side should be either demand or supply, not {loop_side}")

                else:
                    data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
                    data.obs_next.plants[branch_id].outlet_temperature = (
                        data.obs_next.plants[branch_id].inlet_temperature
                    )
                    data.obs_next.plants[component_id].power = torch.tensor([0.], dtype=torch.float32)

        if branch.components.cooling_towers is not None:
            for component_id, component in branch.components.cooling_towers.items():
                if data.acts[component_id].on_off_schedule == 1:
                    cooling_tower_power = component.model.forward(
                        cw_return_water_temperature=data.obs.plants[branch_id].inlet_temperature,
                        cw_return_water_mass_flow_rate=data.acts[loop_id].supply_temperature_sp,
                        cw_supply_water_temperature=data.obs_next.plants[branch_id].outlet_temperature,
                        outside_air_wetbulb_temperature=data.inps.outdoor_temperature,
                    )
                    data.obs_next.plants[component_id].fan_power = cooling_tower_power
                    data.obs_next.plants[branch_id].outlet_temperature = (
                        data.acts[loop_id].supply_temperature_sp
                    )
                    data.obs_next.dc.total_facility_power += cooling_tower_power
                    data.obs_next.dc.total_dc_power += cooling_tower_power
                else:
                    data.obs_next.plants[branch_id].outlet_temperature = (
                        data.obs_next.plants[branch_id].inlet_temperature
                    )
                    data.obs_next.plants[branch_id].water_mass_flow_rate = torch.tensor([0.], dtype=torch.float32)
                    data.obs_next.plants[component_id].fan_power = torch.tensor([0.], dtype=torch.float32)

        # TODO: Add CDU component processing logic here, similar to the ACU component (also a HX :))


    def _solve_half_loop_side_branches(
        self,
        data: Batch,
        loop_id: str,
        loop_side: str,
        loop: SecondaryChilledWaterLoops | ChilledWaterLoops | CondenserWaterLoops,
        this_branches: Dict,
        other_branches: Dict,
    ) -> None:
        """
        The core method to solve the half-loop side branches
        :param data: the data batch
        :param loop_id: the loop id
        :param loop_side: the loop side, supply or demand
        :param this_branches: the branches on the current loop side
        :param other_branches: the branches on the other loop side
        """
        inlet_branch, middle_branches, outlet_branch = self._get_branches(branches=this_branches)
        # step 1: if the branch is on the supply side,
        # we first need to distribute the total demand cooling load and mass flow rate
        if loop_side == "supply":
            self._do_flow_and_load_distribution(
                data=data, loop_id=loop_id, loop=loop, middle_branches=middle_branches
            )
        # step 2: solve the branch component models
        for branch_id, branch in this_branches.items():
            if branch.side == "inlet":
                last_branch = {k: v for k, v in other_branches.items() if v.side == "outlet"}
                # set up branch inlet properties
                self._set_branch_inlet_properties(
                    data=data,
                    current_branch=inlet_branch,
                    last_branch=last_branch,
                    loop_id=loop_id,
                    loop_side=loop_side
                )
                self._solve_branch_components(
                    data=data,
                    loop_id=loop_id,
                    loop_side=loop_side,
                    branch_id=branch_id,
                    branch=branch,
                )
            elif branch.side == "middle":
                self._update_spliter(data=data, split_branch_id=branch_id, inlet_branch=inlet_branch)
                self._solve_branch_components(
                    data=data,
                    loop_id=loop_id,
                    loop_side=loop_side,
                    branch_id=branch_id,
                    branch=branch,
                )
            elif branch.side == "outlet":
                self._update_mixer(data=data, outlet_branch_id=branch_id, mixed_branches=middle_branches)
                self._solve_branch_components(
                    data=data,
                    loop_id=loop_id,
                    loop_side=loop_side,
                    branch_id=branch_id,
                    branch=branch,
                )
            else:
                raise logger.critical(f"Invalid branch side {branch.side}")

    def collect(self, data: dict) -> None:
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

    def learn(self) -> None:
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
        data: Batch,
    ) -> None:
        """
        The forward method of the PlantManager, which iteratively solves the plant by half-loop side branches
        :param data: the data batch
        """
        for loops in [
            self.plant.secondary_chilled_water_loops,
            self.plant.chilled_water_loops,
            self.plant.condenser_water_loops,
        ]:
            if loops is None:
                continue

            for loop_id, loop in loops.items():
                # solve the demand side branches
                self._solve_half_loop_side_branches(
                    data=data,
                    loop_id=loop_id,
                    loop=loop,
                    loop_side="demand",
                    this_branches=loop.demand_branches,
                    other_branches=loop.supply_branches,
                )
                # solve the supply side branches
                self._solve_half_loop_side_branches(
                    data=data,
                    loop_id=loop_id,
                    loop=loop,
                    loop_side="supply",
                    this_branches=loop.supply_branches,
                    other_branches=loop.demand_branches,
                )
                # set the mass flow rate of the main branches (inlet/outlet branches) using the solved demand-side total
                # water mass flow rate
                self._set_main_branch_mass_flow_rate(
                    data=data,
                    loop_id=loop_id,
                    supply_branches=loop.supply_branches,
                    demand_branches=loop.demand_branches,
                )
                # reset the demand-side total cooling load and mass flow rate
                self._reset_demand_side_data(data=data, loop_id=loop_id)
