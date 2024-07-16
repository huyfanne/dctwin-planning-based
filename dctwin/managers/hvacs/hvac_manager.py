from abc import ABC
from datetime import datetime
from typing import Any, Tuple, Dict, List

import torch
import numpy as np

from dclib import Building
from dclib.cooling.plant.loops import Branch, CondenserWaterLoops, SecondaryChilledWaterLoops, ChilledWaterLoops

from dctwin.data import Batch
from dctwin.models.heat_gains import HeatLoadManager
from dctwin.utils import DTEngineConfig
from dctwin.managers.base import BaseManager

from .airloop_manager import AirLoopManager
from .plant_manager import PlantManager
from ..ds import ActionControlVariable


class HVACManager(BaseManager, ABC):
    """ Base class for all data center environments.
    """

    def __init__(
        self,
        config: DTEngineConfig,
        building: Building,
        device_key_mapping: Dict = None
    ) -> None:
        super().__init__(
            config,
            building,
            device_key_mapping
        )

        self.heat_load_manager = HeatLoadManager(
            zones=self._building.constructions.zones,
            device_key_mapping=self._device_key_mapping
        )
        self.air_loop_manager = AirLoopManager(
            zones=self._building.constructions.zones,
            device_key_mapping=self._device_key_mapping
        )
        self.plant_manager = PlantManager(
            device_key_mapping=self._device_key_mapping,
            zones=self._building.constructions.zones,
            plant=self._building.constructions.plant,
        )

        # set up basics
        self._config = config
        self._building = building

        # reset observation and action data
        self._reset_data()

        # others
        self.last_obs = None
        self._timestamp: datetime = datetime.now()

    def _reset_acu_data(self, zone: Any, obs: dict, acts: dict) -> Tuple[dict, dict]:
        for acu_name, acu in zone.constructions.acus.items():
            acts[acu_name] = Batch(
                supply_temperature_sp=(),
                supply_mass_flow_rate_sp=(),
                on_off_schedule=torch.tensor(True, dtype=torch.bool, requires_grad=False),
            )
            obs[acu_name] = Batch(
                supply_air_temperature=torch.tensor(
                    zone.sizing.sizing_zone.zone_cooling_design_supply_air_temperature,
                    dtype=torch.float32,
                    requires_grad=False,
                ),
                supply_air_mass_flow_rate=(),
                fan_power=(),
                return_air_temperature=(),
            )
        return obs, acts

    def _reset_ite_data(self, zone: Any, zone_obs: dict, acts: dict) -> Tuple[dict, dict]:
        for ite_name, ite in zone.constructions.heat_gains.ites.items():
            acts[ite_name] = Batch(
                cpu_load_utilization=(),
            )
        return zone_obs, acts

    def _reset_zone_data(self, obs: dict, acts: dict) -> Tuple[dict, dict]:

        for zone_name, zone in self._building.constructions.zones.items():
            obs[zone_name] = Batch(
                zone_air_temperature=torch.tensor(
                    zone.control_states.thermostats.cooling_setpoint,
                    dtype=torch.float32,
                    requires_grad=False,
                ),
                zone_air_relative_humidity=(),
                sensible_heat_load=(),
            )
            # reset zone facility and IT equipment data
            self._reset_acu_data(zone, obs, acts)
            self._reset_ite_data(zone, obs, acts)

        return obs, acts

    def _reset_plant_data(self, plant_obs: dict, acts: dict) -> Tuple[dict, dict]:

        for loops in [
            self._building.constructions.plant.secondary_chilled_water_loops,
            self._building.constructions.plant.chilled_water_loops,
            self._building.constructions.plant.condenser_water_loops,
        ]:
            if loops is None:
                continue
            for loop_id, loop in loops.items():
                # half-loop demand side components
                plant_obs[loop_id] = {}
                acts[loop_id] = Batch(
                    supply_temperature_sp=(),
                )
                for branch_id, branch in loop.demand_branches.items():
                    plant_obs, plant_acts = self._reset_branch_data(
                        loop=loop,
                        branch_id=branch_id,
                        branch=branch,
                        plant_obs=plant_obs,
                        acts=acts
                    )
                # half-loop supply side components
                for branch_id, branch in loop.supply_branches.items():
                    plant_obs, plant_acts = self._reset_branch_data(
                        loop=loop,
                        branch_id=branch_id,
                        branch=branch,
                        plant_obs=plant_obs,
                        acts=acts,
                    )

        return plant_obs, acts

    def _reset_branch_data(
        self,
        loop: ChilledWaterLoops | CondenserWaterLoops | SecondaryChilledWaterLoops,
        branch_id: str,
        branch: Branch,
        plant_obs: dict,
        acts: dict,
    ) -> Tuple[dict, dict]:
        plant_obs[branch_id] = Batch(
            branch_inlet_temperature=(),
            branch_outlet_temperature=(),
            branch_water_mass_flow_rate=(),
        )
        if branch.components.chillers:
            for chiller_id, chiller in branch.components.chillers.items():
                acts[chiller_id] = Batch(
                    supply_temperature_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                plant_obs[chiller_id] = Batch(
                    power=(),
                )
        if branch.components.pumps:
            for pump_id, pump in branch.components.pumps.items():
                acts[pump_id] = Batch(
                    supply_mass_flow_rate_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                plant_obs[pump_id] = Batch(
                    power=(),
                )
        if branch.components.cooling_towers:
            for tower_id, tower in branch.components.cooling_towers.items():
                acts[tower_id] = Batch(
                    supply_temperature_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                plant_obs[tower_id] = Batch(
                    power=(),
                )
        if branch.components.tanks:
            for tank_id, tank in branch.components.tanks.items():
                acts[tank_id] = Batch(
                    supply_temperature_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                plant_obs[tank_id] = Batch(
                    tank_water_temperature=torch.tensor(
                        loop.sizing.design_loop_exit_temperature,
                        dtype=torch.float32,
                        requires_grad=False,
                    )
                )

        return plant_obs, acts

    def _reset_data(self) -> None:
        acts = {}
        obs = Batch(
            total_dc_power=(),
            facility_power=(),
            ite_demand_power=(),
        )
        zone_obs, plant_obs = {}, {}
        zone_obs, acts = self._reset_zone_data(zone_obs, acts)
        plant_obs, acts = self._reset_plant_data(plant_obs, acts)
        self.data = Batch(
            acts=acts,
            obs=Batch(
                dc=obs,
                zones=zone_obs,
                plants=plant_obs,
            ),
            obs_next=Batch(
                dc=obs,
                zones=zone_obs,
                plants=plant_obs,
            ),
            external_inputs=Batch(
                outdoor_temperature=(),
                electrical_price=(),
                carbon_intensity=(),
            )
        )

    def format_external_inputs(self, external_inputs: Dict | Batch) -> Batch:
        data = Batch()
        for external_input_name, external_input in external_inputs.items():
            data[external_input_name] = torch.tensor(
                [external_input],
                dtype=torch.float32,
                requires_grad=False
            )
        return data

    def format_actions(self, input_data: np.ndarray | torch.Tensor | List, **kwargs) -> Batch:
        _, acts = self._reset_zone_data({}, {})
        _, acts = self._reset_plant_data({}, acts)
        data = Batch(acts=acts)
        ptr = 0
        for act in self.actions:
            if act.control_variable == ActionControlVariable.On_Off_Supervisory:
                variable = torch.tensor(
                    [input_data[ptr]],
                    dtype=torch.bool,
                    requires_grad=False
                )
                data.acts[act.device_unique_key].on_off_schedule = variable

            elif act.control_variable == ActionControlVariable.Temperature_Setpoint:
                if hasattr(data.acts[act.device_unique_key], 'on_off_schedule'):
                    variable = torch.tensor(
                        [input_data[ptr]] if data.acts[act.device_unique_key].on_off_schedule else [0],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad and data.acts[act.device_unique_key].on_off_schedule else False
                    )
                    data.acts[act.device_unique_key].supply_temperature_sp = variable
                else:
                    variable = torch.tensor(
                        [input_data[ptr]],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad else False
                    )
                    data.acts[act.device_unique_key].supply_temperature_sp = variable

            elif (act.control_variable == ActionControlVariable.Fan_Air_Mass_Flow_Rate or
                  act.control_variable == ActionControlVariable.Pump_Mass_Flow_Rate):
                if hasattr(data.acts[act.device_unique_key], 'on_off_schedule'):
                    variable = torch.tensor(
                        [input_data[ptr]] if data.acts[act.device_unique_key].on_off_schedule else [0],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad and data.acts[act.device_unique_key].on_off_schedule else False
                    )
                    data.acts[act.device_unique_key].supply_mass_flow_rate_sp = variable
                else:
                    variable = torch.tensor(
                        [input_data[ptr]],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad else False
                    )
                    data.acts[act.device_unique_key].supply_mass_flow_rate_sp = variable

            elif act.control_variable == ActionControlVariable.CPU_Utilization:
                variable = torch.tensor(
                    [input_data[ptr]],
                    dtype=torch.float32,
                    requires_grad=True if act.requires_grad else False
                )
                data.acts[act.device_unique_key].cpu_load_utilization = variable

            else:
                raise ValueError(f"Unknown control variable {act.control_variable}")

            if variable.requires_grad:
                self.acts_required_grad = torch.cat((self.acts_required_grad, variable))

            ptr += 1
        self.acts_required_grad = self.acts_required_grad.view(-1, 1).detach().numpy()
        self.acts_required_grad = torch.tensor(self.acts_required_grad, dtype=torch.float32, requires_grad=True)
        # re-assign the acts_required_grad to the data
        ptr = 0
        for act in self.actions:
            if act.control_variable == ActionControlVariable.On_Off_Supervisory:
                if data.acts[act.device_unique_key].on_off_schedule.requires_grad:
                    data.acts[act.device_unique_key].on_off_schedule = self.acts_required_grad[ptr]
                    ptr += 1

            elif act.control_variable == ActionControlVariable.Temperature_Setpoint:
                if data.acts[act.device_unique_key].supply_temperature_sp.requires_grad:
                    data.acts[act.device_unique_key].supply_temperature_sp = self.acts_required_grad[ptr]
                    ptr += 1

            elif (act.control_variable == ActionControlVariable.Fan_Air_Mass_Flow_Rate or
                  act.control_variable == ActionControlVariable.Pump_Mass_Flow_Rate):
                if data.acts[act.device_unique_key].supply_mass_flow_rate_sp.requires_grad:
                    data.acts[act.device_unique_key].supply_mass_flow_rate_sp = self.acts_required_grad[ptr]
                    ptr += 1

            elif act.control_variable == ActionControlVariable.CPU_Utilization:
                if data.acts[act.device_unique_key].cpu_load_utilization.requires_grad:
                    data.acts[act.device_unique_key].cpu_load_utilization = self.acts_required_grad[ptr]
                    ptr += 1

        return data.acts

    def format_observations(
        self,
        obs: np.ndarray | torch.Tensor | Batch,
        **kwargs
    ) -> Batch:
        return obs

    def run(
        self,
        acts: Batch,
        obs:  Batch = None,
        external_inputs: Batch = None
    ):
        """
        Run the simulation with the
        :param: states (Batch) current system states,
        :param: actions (Batch) given control signals,
        :return: next system states
        """
        self.data.update(
            acts=acts,
            external_inputs=external_inputs
        )
        if self.heat_load_manager is not None:
            self.heat_load_manager.forward(
                states=self.data.obs.zones,
                actions=self.data.acts
            )
        if self.air_loop_manager is not None:
            self.air_loop_manager.forward(
                states=self.data.obs.zones,
                states_next=self.data.obs_next.zones,
                actions=self.data.acts
            )
        if self.plant_manager is not None:
            self.plant_manager.forward(
                states=self.data.obs,
                states_next=self.data.obs_next,
                actions=self.data.acts,
                external_inputs=self.data.external_inputs
            )
