from abc import ABC
from typing import Dict, List
import json
import torch
import numpy as np
from copy import deepcopy
from datetime import datetime

from dclib import Building

from dctwin.data import Batch
from dctwin.data.scalars import ActionControlType
from dctwin.models.heat_gains import HeatLoadManager
from dctwin.utils import DTEngineConfig
from dctwin.managers.base import BaseManager

from . import AirLoopManager, PlantManager, LiquidLoopManager
from .data import HVACData, actuator_control_type_dict


class HVACManager(BaseManager, ABC):
    """
    Base class for all data center environments.
    """

    def __init__(
        self,
        config: DTEngineConfig,
        log_results: bool = True,
    ) -> None:
        super().__init__(
            config=config,
            log_results=log_results,
        )
        self._model = Building.load(self._config.model_file)
        if self._config.device_key_map:
            with open(self._config.device_key_map, "r") as f:
                self._device_key_mapping = json.load(f)
        else:
            self._device_key_mapping = None
        self._ds = HVACData(model=self._model)
        # set up managers for HVAC sub-systems
        self.heat_load_manager = HeatLoadManager(
            zones=self._model.constructions.zones,
            device_key_mapping=self._device_key_mapping,
        )
        self.liquid_loop_manager = LiquidLoopManager(
            zones=self._model.constructions.zones,
            device_key_mapping=self._device_key_mapping,
        )
        self.air_loop_manager = AirLoopManager(
            zones=self._model.constructions.zones,
            device_key_mapping=self._device_key_mapping,
            time_step=self._time_step,
        )
        self.plant_manager = PlantManager(
            device_key_mapping=self._device_key_mapping,
            plant=self._model.constructions.plant,
            time_step=self._time_step,
        )

    def _reset_data(self) -> None:
        acts = {}
        obs = Batch(
            total_dc_power=torch.tensor([0.], dtype=torch.float32,),
            total_facility_power=torch.tensor([0.], dtype=torch.float32,),
            total_ite_demand_power=torch.tensor([0.], dtype=torch.float32,),
        )
        zone_obs, plant_obs = {}, {}
        zone_obs, acts = self._ds.reset_zone_data(zone_obs, acts)
        plant_obs, acts = self._ds.reset_plant_data(plant_obs, acts)
        self.data = Batch(
            acts=acts,
            obs=Batch(
                dc=obs,
                zones=zone_obs,
                plants=plant_obs,
            ),
            obs_next=Batch(
                dc=deepcopy(obs),
                zones=deepcopy(zone_obs),
                plants=deepcopy(plant_obs),
            ),
            inps=Batch(
                outdoor_air_dry_bulb_temperature=(),
                outdoor_air_wet_bulb_temperature=(),
                outdoor_air_humidity_ratio=(),
                outdoor_air_relative_humidity=(),
                electrical_price=(),
                carbon_intensity=(),
            )
        )
        for obj_name, obj in self.data.obs.zones.items():
            for key in obj.keys():
                self._fieldnames.append(f"{obj_name}:{key}")
        for obj_name, obj in self.data.obs.plants.items():
            for key in obj.keys():
                self._fieldnames.append(f"{obj_name}:{key}")
        for key in self.data.obs.dc.keys():
            self._fieldnames.append(f"{key}")

    @staticmethod
    def _reset_statistics(obs):
        obs.dc.total_dc_power = torch.tensor([0.], dtype=torch.float32)
        obs.dc.total_facility_power = torch.tensor([0.], dtype=torch.float32)
        obs.dc.total_ite_demand_power = torch.tensor([0.], dtype=torch.float32)

    def _update_states(self):
        # overwrite the current states with the next states
        for device_name, device in self.data.obs_next.zones.items():
            for key, value in device.items():
                if isinstance(value, torch.Tensor):
                    self.data.obs.zones[device_name][key] = deepcopy(value.detach())
                else:
                    self.data.obs.zones[device_name][key] = deepcopy(value)

        for device_name, device in self.data.obs_next.plants.items():
            for key, value in device.items():
                if isinstance(value, torch.Tensor):
                    self.data.obs.plants[device_name][key] = deepcopy(value.detach())
                else:
                    self.data.obs.plants[device_name][key] = deepcopy(value)

        for key, value in self.data.obs_next.dc.items():
            if isinstance(value, torch.Tensor):
                self.data.obs.dc[key] = deepcopy(value.detach())
            else:
                self.data.obs.dc[key] = deepcopy(value)

        # update time step
        self._current_time += self._time_step
        if self._ending_timestamp == datetime.fromtimestamp(self._timestamp.timestamp() + self._current_time):
            self.done = True

        # reset plant loop demand side total cooling load and mass flow rate as zero before the next time step begins
        for loops in [
            self.plant_manager.plant.secondary_chilled_water_loops,
            self.plant_manager.plant.chilled_water_loops,
            self.plant_manager.plant.condenser_water_loops,
        ]:
            if loops is None:
                continue
            for loop_id, loop in loops.items():
                self.data.obs_next.plants[loop_id].demand_side_total_cooling_load = (
                    torch.zeros((1,), dtype=torch.float32)
                )
                self.data.obs_next.plants[loop_id].demand_side_total_mass_flow_rate = (
                    torch.zeros((1,), dtype=torch.float32)
                )


    @staticmethod
    def format_external_inputs(inps: Dict | Batch) -> Batch:
        data = Batch()
        for external_input_name, external_input in inps.items():
            data[external_input_name] = torch.tensor(
                [external_input],
                dtype=torch.float32,
                requires_grad=False
            )
        return data

    def format_actions(self, input_data: np.ndarray | torch.Tensor | List) -> Batch:
        """
        Format the actuated actions to the required format for the simulation
        :param input_data: (np.ndarray | torch.Tensor | List) input data
        :return: (Batch) formatted data
        """
        _, acts = self._ds.reset_zone_data({}, {})
        _, acts = self._ds.reset_plant_data({}, acts)
        self._reset_acts_require_grad()
        data = Batch(acts=acts)
        ptr = 0
        for act in self.actions:
            control_type = act.actuator_config.actuated_component_control_type
            actuator_control_type_key = actuator_control_type_dict[control_type]
            device_unique_name = act.actuator_config.actuated_component_unique_name
            if act.control_type == ActionControlType.PRE_SCHEDULED:
                variable = torch.tensor(
                    [next(act)],
                    dtype=torch.float32,
                    requires_grad=False
                )
                data.acts[device_unique_name][actuator_control_type_key] = variable
                ptr -= 1 # pre-scheduled actions do not require a pointer increment

            elif act.control_type == ActionControlType.AGENT_CONTROLLED:
                if hasattr(data.acts[device_unique_name], 'on_off_schedule'):
                    variable = torch.tensor(
                        [input_data[ptr]] if data.acts[
                            device_unique_name].on_off_schedule else [0],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad and data.acts[
                            device_unique_name].on_off_schedule else False
                    )
                    data.acts[device_unique_name][actuator_control_type_key] = variable
                else:
                    variable = torch.tensor(
                        [input_data[ptr]],
                        dtype=torch.float32,
                        requires_grad=True if act.requires_grad else False
                    )
                    data.acts[device_unique_name][actuator_control_type_key] = variable

            else:
                raise ValueError(f"Unknown control type {act.control_type}")

            if variable.requires_grad:
                self._acts_require_grad = torch.cat((self._acts_require_grad, variable))

            ptr += 1
        self._acts_require_grad = self._acts_require_grad.view(-1, 1).detach().numpy()
        self._acts_require_grad = torch.tensor(self._acts_require_grad, dtype=torch.float32, requires_grad=True)

        # re-assign the acts_required_grad to the data
        ptr = 0
        for act in self.actions:
            control_type = act.actuator_config.actuated_component_control_type
            actuator_control_type_key = actuator_control_type_dict[control_type]
            device_unique_name = act.actuator_config.actuated_component_unique_name
            if data.acts[device_unique_name][actuator_control_type_key].requires_grad:
                data.acts[device_unique_name][actuator_control_type_key] = self._acts_require_grad[ptr]
                ptr += 1

        return data.acts

    def collect(self, data: dict):
        self.liquid_loop_manager.collect(data)
        self.air_loop_manager.collect(data)
        self.plant_manager.collect(data)

    def learn(self):
        self.liquid_loop_manager.learn()
        self.air_loop_manager.learn()
        self.plant_manager.learn()

    def run(
        self,
        acts: Batch,
        obs:  Batch = None,
        inps: Batch = None,
    ) -> None:
        """
        Run the simulation with the
        :param: acts (Batch) given control signals,
        :param: obs (Batch) current system states,
        :param: inps (Batch) external inputs
        :return: None
        """
        self._reset_statistics(obs=obs if obs is not None else self.data.obs_next)
        self.data.update(
            acts=acts,
            inps=inps,
            obs=obs if obs is not None else self.data.obs,
        )
        if self.liquid_loop_manager is not None:
            self.liquid_loop_manager.forward(
                data=self.data
            )
        if self.heat_load_manager is not None:
            self.heat_load_manager.forward(
                data=self.data
            )
        if self.air_loop_manager is not None:
            self.air_loop_manager.forward(
                data=self.data
            )
        if self.plant_manager is not None:
            self.plant_manager.forward(
                data=self.data
            )
        # update the states
        self._update_states()
        # log the data
        if self._log_results:
            self._post_process({**self.data.obs.zones, **self.data.obs.plants, **self.data.obs.dc})
