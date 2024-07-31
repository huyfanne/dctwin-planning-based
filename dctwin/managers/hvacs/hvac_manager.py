import csv
from abc import ABC
from typing import Dict, List
from pathlib import Path

import torch
import numpy as np
from copy import deepcopy

from dclib import Building

from dctwin.data import Batch
from dctwin.models.heat_gains import HeatLoadManager
from dctwin.utils import DTEngineConfig
from dctwin.managers.base import BaseManager

from .airloop_manager import AirLoopManager
from .plant_manager import PlantManager
from ..ds import ActionControlVariable
from .ds import HVACData


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
            config=config,
            model=building,
            device_key_mapping=device_key_mapping,
            ds=HVACData(model=building)
        )
        # set up managers for HVAC sub-systems
        self.heat_load_manager = HeatLoadManager(
            zones=self._model.constructions.zones,
            device_key_mapping=self._device_key_mapping
        )
        self.air_loop_manager = AirLoopManager(
            zones=self._model.constructions.zones,
            device_key_mapping=self._device_key_mapping
        )
        self.plant_manager = PlantManager(
            device_key_mapping=self._device_key_mapping,
            plant=self._model.constructions.plant,
            time_step=self._time_step,
        )
        # set up the result logging
        self._pre_process(
            log_dir=config.logging_config.log_dir
        )
        self._current_time = 0

    def _reset_data(self) -> None:
        acts = {}
        obs = Batch(
            total_dc_power=(),
            facility_power=(),
            ite_demand_power=(),
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
                outdoor_temperature=(),
                electrical_price=(),
                carbon_intensity=(),
            )
        )

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

    def _pre_process(self, log_dir: str) -> None:
        """
        Create the log file for the simulation results
        """
        fieldnames = ["Timestamp"]
        for obj_name, obj in self.data.obs.zones.items():
            for key in obj.keys():
                fieldnames.append(f"{obj_name}:{key}")
        for obj_name, obj in self.data.obs.plants.items():
            for key in obj.keys():
                fieldnames.append(f"{obj_name}:{key}")
        log_dir = Path(f"logs/{log_dir}")
        log_dir.mkdir(parents=True, exist_ok=True)
        self.file_handler = open(log_dir.joinpath("output.csv"), "wt", newline='')
        self.log_handler = csv.DictWriter(
            self.file_handler,
            fieldnames=fieldnames
        )
        self.log_handler.writeheader()
        self.file_handler.flush()

    def _post_processing(self, ):
        """
        Log the simulation results
        """
        log_dict = {}
        log_dict.update(
            {"Timestamp": self._current_time}
        )
        for obj_name, obj in self.data.obs.zones.items():
            for key in obj.keys():
                try:
                    log_dict.update({f"{obj_name}:{key}": obj[key].item()})
                except:
                    log_dict.update({f"{obj_name}:{key}": 0.})
        for obj_name, obj in self.data.obs.plants.items():
            for key in obj.keys():
                try:
                    log_dict.update({f"{obj_name}:{key}": obj[key].item()})
                except:
                    log_dict.update({f"{obj_name}:{key}": 0.})
        self.log_handler.writerow(log_dict)
        self.file_handler.flush()

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
        _, acts = self._ds.reset_zone_data({}, {})
        _, acts = self._ds.reset_plant_data({}, acts)
        self._reset_acts_required_grad()
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

            elif act.control_variable == ActionControlVariable.Tank_Source_Side_Mass_Flow_Rate:
                variable = torch.tensor(
                    [input_data[ptr]],
                    dtype=torch.float32,
                    requires_grad=True if act.requires_grad else False
                )
                data.acts[act.device_unique_key].source_side_mass_flow_rate = variable

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

            elif act.control_variable == ActionControlVariable.Tank_Source_Side_Mass_Flow_Rate:
                if data.acts[act.device_unique_key].source_side_mass_flow_rate.requires_grad:
                    data.acts[act.device_unique_key].source_side_mass_flow_rate = self.acts_required_grad[ptr]
                    ptr += 1

        return data.acts

    def run(
        self,
        acts: Batch,
        obs:  Batch = None,
        inps: Batch = None
    ) -> None:
        """
        Run the simulation with the
        :param: states (Batch) current system states,
        :param: actions (Batch) given control signals,
        :return: next system states
        """
        self.data.update(
            acts=acts,
            inps=inps
        )
        if self.heat_load_manager is not None:
            self.heat_load_manager.forward(
                states=self.data.obs_next.zones,
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
                data=self.data,
            )
        # update the states
        self._update_states()
        # log the data
        self._post_processing()
