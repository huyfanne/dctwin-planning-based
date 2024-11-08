import torch
from typing import Any, Dict, Tuple

from dclib import Building, Room
from dclib.cooling.common.loop import Branch

from dctwin.data import Batch
from dctwin.data.scalars import ActuatorControlType


actuator_control_type_dict = {
    ActuatorControlType.On_Off_Supervisory: "on_off_schedule",
    ActuatorControlType.Temperature_Setpoint: "supply_temperature_sp",
    ActuatorControlType.Fan_Air_Mass_Flow_Rate: "supply_mass_flow_rate_sp",
    ActuatorControlType.Pump_Mass_Flow_Rate: "supply_mass_flow_rate_sp",
    ActuatorControlType.CPU_Utilization: "cpu_load_utilization",
    ActuatorControlType.Tank_Source_Side_Mass_Flow_Rate: "source_side_mass_flow_rate",
    ActuatorControlType.Relative_Humidity_Setpoint: "relative_humidity_sp",
}


class HVACData:
    """The class to reset the HVAC data for the environment, including zones and plant.
    """

    def __init__(self, model: Building):
        self._model = model

    @staticmethod
    def _reset_d2c_server_data(zone: Room, obs: dict, acts: dict) -> Tuple[dict, dict]:
        if zone.constructions.liquid_flow_networks is None:
            return obs, acts
        for fluid_network_name, fluid_network in zone.constructions.liquid_flow_networks.items():
            for demand_branch_name, demand_branch in fluid_network.demand_branches.items():
                if demand_branch.components.servers is not None:
                    for server_name, server in demand_branch.components.servers.items():
                        obs[server_name] = Batch(
                            max_chip_temperature=(),
                            liquid_inlet_temperature=(),
                            liquid_outlet_temperature=(),
                            power=(),
                        )
        return obs, acts

    @staticmethod
    def _reset_acu_data(zone: Any, obs: dict, acts: dict) -> Tuple[dict, dict]:
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
                supply_air_relative_humidity=(),
                return_air_temperature=(),
                return_air_relative_humidity=(),
                coil_sensible_heat_load=(),
                fan_power=(),
            )
        return obs, acts

    @staticmethod
    def _reset_dehumidifier_data(zone: Any, obs: dict, acts: dict) -> Tuple[dict, dict]:
        if zone.constructions.dehumidifiers is None:
            return obs, acts
        for dehumidifier_name, dehumidifier in zone.constructions.dehumidifiers.items():
            acts[dehumidifier_name] = Batch(
                on_off_schedule=torch.tensor([False], dtype=torch.bool, requires_grad=False),
                relative_humidity_sp=(),
            )
            obs[dehumidifier_name] = Batch(
                inlet_air_temperature=(),
                outlet_air_temperature=(),
                supply_air_mass_flow_rate=(),
                inlet_air_relative_humidity=(),
                outlet_air_relative_humidity=(),
                inlet_air_humidity_ratio=(),
                outlet_air_humidity_ratio=(),
                water_removal_rate=(),
                power=(),
            )
        return obs, acts

    @staticmethod
    def _reset_cdu_data(zone: Room, obs: dict, acts: dict) -> Tuple[dict, dict]:
        if zone.constructions.liquid_flow_networks is None:
            return obs, acts
        for fluid_network_name, fluid_network in zone.constructions.liquid_flow_networks.items():
            for supply_branch_name, supply_branch in fluid_network.supply_branches.items():
                if supply_branch.components.cdus is not None:
                    for cdu_name, cdu in supply_branch.components.cdus.items():
                        acts[cdu_name] = Batch(
                            supply_temperature_sp=(),
                            supply_mass_flow_rate_sp=(),
                            on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                        )
                        obs[cdu_name] = Batch(
                            coil_sensible_heat_load=(),
                            cooling_water_supply_temperature=(),
                            cooling_water_return_temperature=(),
                            chilled_water_supply_temperature=(),
                            chilled_water_return_temperature=(),
                            chilled_water_mass_flow_rate=(),
                            cooling_water_mass_flow_rate=(),
                            electrical_power=()
                        )
        return obs, acts

    @staticmethod
    def _reset_ite_data(zone: Any, zone_obs: dict, acts: dict) -> Tuple[dict, dict]:
        if zone.constructions.heat_gains is None or zone.constructions.heat_gains.ites is None:
            return zone_obs, acts
        for ite_name, ite in zone.constructions.heat_gains.ites.items():
            acts[ite_name] = Batch(
                cpu_load_utilization=(),
            )
        return zone_obs, acts

    @staticmethod
    def _reset_branch_components_data(
        obs: Dict,
        acts: Dict,
        branch_id: str,
        branch: Branch,
    ) -> Tuple[Dict, Dict]:
        if branch.components.chillers:
            for chiller_id, chiller in branch.components.chillers.items():
                if len(branch.components.chillers) > 1:
                    raise ValueError("Only one chiller is allowed in a branch")
                acts[chiller_id] = Batch(
                    supply_temperature_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                obs[chiller_id] = Batch(
                    power=(),
                    cooling_load=(),
                    evaporator_inlet_temperature=(),
                    evaporator_outlet_temperature=(),
                    condenser_inlet_temperature=(),
                    condenser_outlet_temperature=(),
                )
        if branch.components.pumps:
            for pump_id, pump in branch.components.pumps.items():
                acts[pump_id] = Batch(
                    supply_mass_flow_rate_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                obs[pump_id] = Batch(
                    power=()
                )
        if branch.components.cooling_towers:
            for tower_id, tower in branch.components.cooling_towers.items():
                acts[tower_id] = Batch(
                    supply_temperature_sp=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                obs[tower_id] = Batch(
                    fan_power=(),
                    cooling_load=(),
                    inlet_temperature=(),
                    outlet_temperature=(),
                    water_mass_flow_rate=(),
                    air_mass_flow_rate=(),
                    heat_transfer_rate=()
                )
        if branch.components.tanks:
            tank_water_temperature = torch.zeros(1,)
            for tank_id, tank in branch.components.tanks.items():
                if len(branch.components.tanks) > 1:
                    raise ValueError("Only one tank is allowed in a branch")
                acts[tank_id] = Batch(
                    supply_temperature_sp=(),
                    use_side_inlet_temperature_sp=(),
                    source_side_mass_flow_rate=(),
                    on_off_schedule=torch.tensor([True], dtype=torch.bool, requires_grad=False),
                )
                obs[tank_id] = Batch(
                    tank_water_temperature=torch.tensor(
                        [21.0],  # initial tank temperature
                        dtype=torch.float32,
                        requires_grad=False,
                    ),
                    use_side_mass_flow_rate=(),
                    source_side_mass_flow_rate=(),
                    use_side_cooling_load=(),
                    source_side_cooling_load=(),
                    use_side_inlet_temperature=(),
                    use_side_outlet_temperature=(),
                    source_side_inlet_temperature=(),
                    source_side_outlet_temperature=(),
                )
                tank_water_temperature += obs[tank_id].tank_water_temperature
            obs[branch_id].outlet_temperature = tank_water_temperature / len(branch.components.tanks)

        return obs, acts

    def _reset_half_loop_side_branches(
        self,
        obs: Dict,
        acts: Dict,
        branches: Dict[str, Branch],
    ) -> Tuple[dict, dict]:
        inlet_branch, middle_branches, outlet_branch = {}, {}, {}

        for branch_id, branch in branches.items():
            obs[branch_id] = Batch(
                inlet_temperature=(),
                outlet_temperature=(),
                water_mass_flow_rate=(),
            )
            if branch.side == "inlet":
                inlet_branch.update({branch_id: branch})
                obs, act = self._reset_branch_components_data(obs, acts, branch_id, branch)

            if branch.side == "middle":
                middle_branches.update({branch_id: branch})
                obs, act = self._reset_branch_components_data(obs, acts, branch_id, branch)

            if branch.side == "outlet":
                outlet_branch.update({branch_id: branch})
                obs, act = self._reset_branch_components_data(obs, acts, branch_id, branch)
                mixed_water_temperature = torch.zeros(1,)
                for middle_branch_id, middle_branch in middle_branches.items():
                    if len(obs[middle_branch_id].outlet_temperature) != 0:
                        mixed_water_temperature += obs[middle_branch_id].outlet_temperature
                obs[branch_id].inlet_temperature = mixed_water_temperature / len(middle_branches)

        return obs, acts

    def reset_zone_data(self, obs: dict, acts: dict) -> Tuple[dict, dict]:
        for zone_name, zone in self._model.constructions.zones.items():
            obs[zone_name] = Batch(
                zone_air_temperature=torch.tensor(
                    zone.control_states.thermostats.cooling_setpoint,
                    dtype=torch.float32,
                    requires_grad=False,
                ),
                zone_air_relative_humidity=(
                    torch.tensor(
                        [0.6], # initial relative humidity
                        dtype=torch.float32,
                        requires_grad=False,
                    )
                ),
                zone_air_humidity_ratio=(),
                sensible_heat_load=(),
                zone_moisture=(),
            )
            # reset zone facility and IT equipment data
            self._reset_d2c_server_data(zone, obs, acts)
            self._reset_acu_data(zone, obs, acts)
            self._reset_dehumidifier_data(zone, obs, acts)
            self._reset_cdu_data(zone, obs, acts)
            self._reset_ite_data(zone, obs, acts)
        return obs, acts

    def reset_plant_data(self, obs: dict, acts: dict) -> Tuple[dict, dict]:
        for loops in [
            self._model.constructions.plant.secondary_chilled_water_loops,
            self._model.constructions.plant.chilled_water_loops,
            self._model.constructions.plant.condenser_water_loops,
        ]:

            if loops is None:
                continue

            for loop_id, loop in loops.items():
                obs[loop_id] = Batch(
                    demand_side_total_mass_flow_rate=(
                        torch.tensor(
                            [0.],
                            dtype=torch.float32,
                        )
                    ),
                    demand_side_total_cooling_load=(
                        torch.tensor(
                            [0.],
                            dtype=torch.float32,
                        )
                    ),
                )
                acts[loop_id] = Batch(
                    supply_temperature_sp=(),
                )
                self._reset_half_loop_side_branches(
                    obs=obs,
                    acts=acts,
                    branches=loop.demand_branches,
                )
                self._reset_half_loop_side_branches(
                    obs=obs,
                    acts=acts,
                    branches=loop.supply_branches,
                )

        return obs, acts
