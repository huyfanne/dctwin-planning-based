from pathlib import Path

from sympy import Symbol, Add

from dctwin.utils import (
    EPlusActionConfig,
    EPlusObservationConfig,
    EPlusEnvConfig,
    SimulationTimeConfig,
)

from loguru import logger
import xml.etree.ElementTree as ET
from typing import List, Union, Optional

import numpy as np
import opyplus as op
from opyplus.exceptions import RecordDoesNotExistError


class Eplus:
    """
    Class for reading template Eplus .idf input file, getting meta info and equipment info of the input file, setting
    user specified external schedule, actuator and output variables, and modifying the run period parameters for the
    simulation
    """

    variable_name_nodes = [
        "System Node Temperature",
        "System Node Mass Flow Rate",
        "System Node Pressure",
    ]
    variable_name_it_equipment = [
        "ITE CPU Electricity Rate",
        "ITE Fan Electricity Rate",
        "ITE UPS Electricity Rate",
        "ITE UPS Heat Gain to Zone Rate",
        "ITE Total Heat Gain to Zone Rate",
        "ITE Air Mass Flow Rate",
        "ITE Air Inlet Dry-Bulb Temperature",
        "ITE Air Outlet Dry-Bulb Temperature",
        "ITE Supply Heat Index",
    ]
    variable_name_thermal_zone = [
        "Zone Outdoor Air Drybulb Temperature",
        "Zone Air Temperature",
        "Zone Air Humidity Ratio",
        "Zone Air Heat Balance Internal Convective Heat Gain Rate",
        "Zone Air Heat Balance Surface Convection Rate",
        "Zone Air System Sensible Cooling Rate",
    ]
    variable_name_whole_building = [
        "Facility Total HVAC Electricity Demand Rate",
        "Facility Total Electricity Demand Rate",
        "Facility Total Building Electricity Demand Rate",
    ]

    variable_name_ems = ["Power Usage Effectiveness"]

    def __init__(self, epm: op.Epm, chw_loop_prefix: str = "CHW") -> None:
        self.epm = epm
        self.node_names = self._get_node_names()
        self.branch_name = self._get_branch_names()
        self.component_names = self._get_component_names()
        self.zone_names = self._get_zone_names()
        self.thermostats_name = self._get_thermostat_setpoints_name()
        self.acu_fan_names = self._get_acu_fan_info()
        self.supply_air_node_names = self._get_supply_air_node_info()
        self.chw_water_supply_nodes = self._get_chw_water_supply_nodes(chw_loop_prefix)
        self.valid_key_values = self._get_valid_key_values()
        self.zone_inlet_nodes = self._get_zone_inlet_nodes()
        self.zone_ite_equipments = self._get_it_equipment()
        self.zone_iec_primary_outlet_nodes = self._get_iec_primary_outlet_nodes()
        self.zone_dec_outlet_nodes = self._get_dec_outlet_nodes()
        self._get_design_parameters()
        self._get_curve_parameters()

        self.air_density = 1.19
        self.air_cp = 1006

    @classmethod
    def load(cls, idf_path: str) -> "Eplus":
        """
        Load the EnergyPlus model from the idf file
        """
        epm = op.Epm.load(idf_path)
        return cls(epm)

    "-------------------------------------Internal IDF Parsing Function API--------------------------------------------"

    def _get_thermostat_setpoints_name(self):
        """
        Get the name for all Thermostat:DualSetpoints object name in EnergyPlus
        """
        thermostat_setpoints_name = []
        for thermostat_setpoints in self.epm.thermostatsetpoint_dualsetpoint:
            thermostat_setpoints_name.append(thermostat_setpoints.name)
        return thermostat_setpoints_name

    def _get_iec_primary_outlet_nodes(self):
        """
        Get primary air outlet node name for each zone Indirect Evaporate Cooler (IEC)
        """
        iec_primary_outlet_nodes = []
        for iec in self.epm.EvaporativeCooler_Indirect_ResearchSpecial:
            iec_primary_outlet_nodes.append(iec.primary_air_outlet_node_name)
        return iec_primary_outlet_nodes

    def _get_dec_outlet_nodes(self):
        """
        Get air outlet node name for each zone direct Evaporate Cooler (DEC)
        """
        dec_outlet_nodes = []
        for dec in self.epm.EvaporativeCooler_Direct_ResearchSpecial:
            dec_outlet_nodes.append(dec.air_outlet_node_name)
        return dec_outlet_nodes

    def _get_it_equipment(self):
        """
        Get all ElectricEquipment:ITE:AirCooled objects for all thermal zones
        """
        it_equipment = []
        for equipment in self.epm.ElectricEquipment_ITE_AirCooled:
            it_equipment.append(equipment)
        return it_equipment

    def _get_zone_inlet_nodes(self):
        """
        Get zone inlet nodes for all thermal zones
        """
        zone_inlet_nodes = []
        for zone_connection in self.epm.ZoneHVAC_EquipmentConnections.select():
            inlet_nodes_name = zone_connection.zone_air_inlet_node_or_nodelist_name
            match_fn = lambda x: x.name == inlet_nodes_name
            node_list = self.epm.NodeList.one(match_fn)
            for attribute in dir(node_list):
                if attribute != "name" and not attribute.startswith("_"):
                    zone_inlet_nodes.append(getattr(node_list, attribute))
        return zone_inlet_nodes

    def _get_zone_names(self):
        """
        Get all zone names
        """
        zone_names = set()
        zones = self.epm.Zone
        for zone in zones:
            zone_names.add(zone.name)
        return zone_names

    def _get_node_names(self):
        """
        Get all node names
        """
        node_names = set()
        branches = self.epm.Branch
        for branch in branches:
            # one branch can have multiple components
            num_components = int((len(branch) - 2) / 4)
            for idx in range(num_components):
                node_names.add(branch[f"component_{idx + 1}_inlet_node_name"])
                node_names.add(branch[f"component_{idx + 1}_outlet_node_name"])
        for atu in self.epm.ZoneHVAC_AirDistributionUnit:
            node_names.add(atu.air_distribution_unit_outlet_node_name)
        for mix in self.epm.AirLoopHVAC_ZoneMixer:
            node_names.add(mix.outlet_node_name)
        return node_names

    def _get_branch_names(self):
        branch_names = set()
        branches = self.epm.Branch
        for branch in branches:
            branch_names.add(branch.name)
        return branch_names

    def _get_component_names(self):
        """
        Get all components name
        """
        component_names = set()
        branches = self.epm.Branch
        for branch in branches:
            num_components = int((len(branch) - 2) / 4)
            for idx in range(num_components):
                component_names.add(branch[f"component_{idx + 1}_name"].name)
        for equipment in self.epm.ElectricEquipment_ITE_AirCooled:
            if equipment.cpu_loading_schedule_name is not None:
                component_names.add(equipment.cpu_loading_schedule_name.name)
        return component_names

    def _get_acu_fan_info(self) -> List:
        """
        Get the acu fan info, including fan outlet node name (can be placed a temperature set point) and fan name (can
        be actuated the air mass flow rate)
        """
        vsd_fans = self.epm.Fan_VariableVolume
        fan_list = []
        for vsd_fan in vsd_fans:
            fan_list.append(vsd_fan.name)
        return fan_list

    def _get_supply_air_node_info(self):
        """
        Get the acu supply air node info
        """
        supply_air_nodes = self.epm.AirLoopHVAC
        node_list = []
        for node in supply_air_nodes:
            node_list.append(node.supply_side_outlet_node_names)
        return node_list

    def _get_chw_water_supply_nodes(self, plant_type="CHW"):
        """
        Get all chilled water supply nodes in PlantLoops (can be placed with a temperature set point)
        """
        chw_supply_outlet_node_names = []
        plant_loops = self.epm.PlantLoop
        for plant_loop in plant_loops:
            # we assume that all chilled water loops start with "chw" and all condenser water loops start with "cw"
            if plant_loop.name.startswith(plant_type.lower()):
                chw_supply_outlet_node_names.append(
                    plant_loop.plant_side_outlet_node_name
                )
        return chw_supply_outlet_node_names

    def _get_valid_key_values(self):
        valid_key_values = (
            self.node_names
            | self.component_names
            | self.zone_names
            | {"Whole Building"}
            | {"whole building"}
        )
        it_equipment = self.epm.ElectricEquipment_ITE_AirCooled.select()
        supply_air_nodes = set()
        ite_names = set()
        for equipment in it_equipment:
            supply_air_nodes.add(equipment.supply_air_node_name)
            ite_names.add(equipment.name)
        valid_key_values |= supply_air_nodes | ite_names
        return valid_key_values

    @staticmethod
    def _get_biquadratic_curve_coefficient(record) -> List:
        return [
            record.coefficient1_constant,
            record.coefficient2_x,
            record.coefficient3_x_2,
            record.coefficient4_y,
            record.coefficient5_y_2,
            record.coefficient6_x_y,
            record.minimum_value_of_x,
            record.maximum_value_of_x,
            record.minimum_value_of_y,
            record.maximum_value_of_y,
            record.minimum_curve_output,
            record.maximum_curve_output,
        ]

    @staticmethod
    def _get_quadractic_curve_coefficient(record) -> List:
        return [
            record.coefficient1_constant,
            record.coefficient2_x,
            record.coefficient3_x_2,
        ]

    def _get_curve_parameters(self) -> None:
        self.power_as_load_temp_parameter = {}
        self.flow_as_load_temp_parameter = {}
        self.power_as_fan_flow_parameter = {}
        self.ups_efficiency_as_load_factor = {}
        for it_equipment in self.epm.ElectricEquipment_ITE_AirCooled.select():
            name = it_equipment.name
            self.power_as_load_temp_parameter[
                name
            ] = self._get_biquadratic_curve_coefficient(
                it_equipment.cpu_power_input_function_of_loading_and_air_temperature_curve_name
            )
            self.flow_as_load_temp_parameter[
                name
            ] = self._get_biquadratic_curve_coefficient(
                it_equipment.air_flow_function_of_loading_and_air_temperature_curve_name
            )
            self.power_as_fan_flow_parameter[
                name
            ] = self._get_quadractic_curve_coefficient(
                it_equipment.fan_power_input_function_of_flow_curve_name
            )
            self.ups_efficiency_as_load_factor[
                name
            ] = self._get_quadractic_curve_coefficient(
                it_equipment.electric_power_supply_efficiency_function_of_part_load_ratio_curve_name
            )

    """-------------------------------Internal Curve Management API----------------------------------------"""

    def _get_design_parameters(self) -> None:
        self.design_power_input = {}
        self.design_fraction_cpu = {}
        self.design_fraction_fan = {}
        self.design_power_input = {}
        self.design_cpu_utilization = {}
        self.design_air_volumetric_flow_rate = {}
        self.ups_efficiency = {}
        self.design_cpu_power = {}
        self.design_fan_power = {}
        self.design_flow_rate_per_watt = {}
        self.number_of_units = {}
        for it_equipment in self.epm.ElectricEquipment_ITE_AirCooled.select():
            name = it_equipment.name
            self.design_power_input[name] = it_equipment.watts_per_unit
            self.number_of_units[name] = it_equipment.number_of_units
            self.design_fraction_fan[
                name
            ] = it_equipment.design_fan_power_input_fraction
            self.design_fraction_cpu[name] = 1.0 - self.design_fraction_fan[name]
            self.design_cpu_utilization[
                name
            ] = it_equipment.design_power_input_schedule_name.hourly_value
            self.ups_efficiency[
                name
            ] = it_equipment.design_electric_power_supply_efficiency
            self.design_cpu_power[name] = (
                self.design_power_input[name] * self.design_fraction_cpu[name]
            )
            self.design_fan_power[name] = (
                self.design_power_input[name] * self.design_fraction_fan[name]
            )
            self.design_flow_rate_per_watt[
                name
            ] = it_equipment.design_fan_air_flow_rate_per_power_input
            self.design_air_volumetric_flow_rate[name] = (
                self.design_flow_rate_per_watt[name] * self.design_power_input[name]
            )

    def _fun_power_as_load_temp(
        self,
        cpu_loading: Union[float, np.ndarray],
        server_inlet_temperature: Union[float, np.ndarray, Symbol],
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute CPU power factor with cpu utilization and server inlet temperature
        """
        constant = self.power_as_load_temp_parameter[name][0]
        coef_cpu = self.power_as_load_temp_parameter[name][1]
        coef_cpu_squre = self.power_as_load_temp_parameter[name][2]
        coef_in_temp = self.power_as_load_temp_parameter[name][3]
        coef_in_temp_squre = self.power_as_load_temp_parameter[name][4]
        coef_cross = self.power_as_load_temp_parameter[name][5]
        min_x = self.power_as_load_temp_parameter[name][6]
        max_x = self.power_as_load_temp_parameter[name][7]
        min_y = self.power_as_load_temp_parameter[name][8]
        max_y = self.power_as_load_temp_parameter[name][9]
        min_factor = self.power_as_load_temp_parameter[name][10]
        max_factor = self.power_as_load_temp_parameter[name][11]
        cpu_loading = np.clip(cpu_loading, min_x, max_x)
        if not isinstance(server_inlet_temperature, Symbol):
            server_inlet_temperature = np.clip(server_inlet_temperature, min_y, max_y)
        factor = (
            constant
            + cpu_loading * coef_cpu
            + cpu_loading**2 * coef_cpu_squre
            + server_inlet_temperature * coef_in_temp
            + server_inlet_temperature**2 * coef_in_temp_squre
            + cpu_loading * server_inlet_temperature * coef_cross
        )
        return (
            np.clip(factor, min_factor, max_factor)
            if not isinstance(factor, Add)
            else factor
        )

    def _fun_flow_as_load_temp(
        self,
        cpu_loading: Union[float, np.ndarray],
        server_inlet_temperature: Union[float, np.ndarray, Symbol],
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute volumetric air flow rate factor for each server with cpu utilization and server inlet temperature
        """
        constant = self.flow_as_load_temp_parameter[name][0]
        coef_cpu = self.flow_as_load_temp_parameter[name][1]
        coef_cpu_squre = self.flow_as_load_temp_parameter[name][2]
        coef_in_temp = self.flow_as_load_temp_parameter[name][3]
        coef_in_temp_squre = self.flow_as_load_temp_parameter[name][4]
        coef_cross = self.flow_as_load_temp_parameter[name][5]
        min_x = self.flow_as_load_temp_parameter[name][6]
        max_x = self.flow_as_load_temp_parameter[name][7]
        min_y = self.flow_as_load_temp_parameter[name][8]
        max_y = self.flow_as_load_temp_parameter[name][9]
        min_factor = self.flow_as_load_temp_parameter[name][10]
        max_factor = self.flow_as_load_temp_parameter[name][11]
        cpu_loading = np.clip(cpu_loading, min_x, max_x)
        if not isinstance(server_inlet_temperature, Symbol):
            server_inlet_temperature = np.clip(server_inlet_temperature, min_y, max_y)
        factor = (
            constant
            + cpu_loading * coef_cpu
            + cpu_loading**2 * coef_cpu_squre
            + server_inlet_temperature * coef_in_temp
            + server_inlet_temperature**2 * coef_in_temp_squre
            + cpu_loading * server_inlet_temperature * coef_cross
        )
        return (
            np.clip(factor, min_factor, max_factor)
            if not isinstance(factor, Add)
            else factor
        )

    def _fun_power_as_flow(
        self,
        air_flow_rate_factor: Union[float, np.ndarray],
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute fan power factor for each server with volumetric air flow rate factor
        """
        constant = self.power_as_fan_flow_parameter[name][0]
        coef_air_flow_rate_factor = self.power_as_fan_flow_parameter[name][1]
        coef_air_flow_rate_factor_square = self.power_as_fan_flow_parameter[name][2]
        factor = (
            constant
            + coef_air_flow_rate_factor * air_flow_rate_factor
            + coef_air_flow_rate_factor_square * air_flow_rate_factor**2
        )
        return factor

    def _fun_ups_efficiency_as_partial_load(
        self,
        partial_load_factor: float,
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute UPS efficiency loss factor with UPS Partial Load Factor (PLR)
        """
        constant = self.ups_efficiency_as_load_factor[name][0]
        coef_plr = self.ups_efficiency_as_load_factor[name][1]
        coef_plr_square = self.ups_efficiency_as_load_factor[name][2]
        factor = (
            constant
            + coef_plr * partial_load_factor
            + coef_plr_square * partial_load_factor**2
        )
        return factor

    """-------------------------------Internal IDF Modification Function API----------------------------------------"""

    def _set_external_schedule(self, config: EPlusActionConfig) -> None:
        """
        Set Eplus ExternalInterface:Schedule according to config
        """

        def _set_cpu_load_schedule() -> None:
            ite_equipment_name = schedule_config.scheduled_ite_equipment_name
            ite = self.epm.ElectricEquipment_ITE_AirCooled.select(
                lambda x: x.name == ite_equipment_name.lower()
            ).one()
            ite.cpu_loading_schedule_name = config.variable_name

        def _set_delta_temp_supply_schedule() -> None:
            ite_equipment_name = schedule_config.scheduled_ite_equipment_name
            ite = self.epm.ElectricEquipment_ITE_AirCooled.select(
                lambda x: x.name == ite_equipment_name.lower()
            ).one()
            ite.supply_temperature_difference_schedule = config.variable_name

        def _set_delta_temp_return_schedule() -> None:
            ite_equipment_name = schedule_config.scheduled_ite_equipment_name
            ite = self.epm.ElectricEquipment_ITE_AirCooled.select(
                lambda x: x.name == ite_equipment_name.lower()
            ).one()
            ite.return_temperature_difference_schedule = config.variable_name

        def _set_room_setpoint_schedule() -> None:
            thermostat_setpoint_name = (
                schedule_config.scheduled_thermostat_setpoint_name
            )
            thermostat_setpoint = self.epm.thermostatsetpoint_dualsetpoint.select(
                lambda x: x.name == thermostat_setpoint_name.lower()
            ).one()
            thermostat_setpoint.cooling_setpoint_temperature_schedule_name = (
                config.variable_name
            )

        func_dict = {
            "ITE": _set_cpu_load_schedule,
            "ITEDeltaTSupply": _set_delta_temp_supply_schedule,
            "ITEDeltaTReturn": _set_delta_temp_return_schedule,
            "Room": _set_room_setpoint_schedule,
        }

        name = config.variable_name
        schedule_config = config.schedule_config
        # first add ScheduleTypeLimit according to the lower and upper bound value specified in the input dict
        schedule_type_limits_name = "{:s} schedule type limit".format(name)
        self.epm.ScheduleTypeLimits.add(
            name=schedule_type_limits_name,
            lower_limit_value=schedule_config.lb,
            upper_limit_value=schedule_config.ub,
            numeric_type="CONTINUOUS",
        )

        # check if the external schedule is already exist in the idf file
        if (
            len(
                self.epm.ExternalInterface_Schedule.select(
                    lambda x: x.name == name.lower()
                )
            )
            > 0
        ):
            sch = self.epm.ExternalInterface_Schedule.select(
                lambda x: x.name == name.lower()
            )
            sch.delete()

        # add external schedule
        self.epm.ExternalInterface_Schedule.add(
            name=name,
            schedule_type_limits_name=schedule_type_limits_name,
            initial_value=schedule_config.initial_value,
        )

        # set setpoint/ITE schedule/AirLoopHVAC
        schedule_type = schedule_config.DESCRIPTOR.EnumValueName(
            "ScheduleType", schedule_config.schedule_type
        )
        func_dict[schedule_type]()

    def _set_external_actuator(self, config: EPlusActionConfig) -> None:
        """
        Set Eplus ExternalInterface:Actuator according to config
        """
        name = config.variable_name
        actuator_config = config.actuator_config
        # check whether the actuated component name is valid

        if actuator_config.actuated_component_unique_name.lower() not in set.union(
            self.component_names, self.node_names, self.branch_name
        ):
            raise ValueError(
                f"Actuated Component Unique Name : {actuator_config.actuated_component_unique_name} is not defined in "
                f"IDF file."
            )

        # check if the external schedule is already exist in the idf file
        if (
            self.epm.ExternalInterface_Actuator.select(lambda x: x.name == name.lower())
            is not None
        ):
            act = self.epm.ExternalInterface_Actuator.select(
                lambda x: x.name == name.lower()
            )
            act.delete()

        # add actuator
        actuated_component_unique_name = actuator_config.actuated_component_unique_name
        component_type = actuator_config.DESCRIPTOR.EnumValueName(
            "ComponentType", actuator_config.actuated_component_type
        )
        component_type = (
            " ".join(component_type.split("_"))
            if not component_type.startswith("Schedule")
            else ":".join(component_type.split("_"))
        )
        # here we must use "on/off" instead of "on off" as stated by EnergyPlus :)
        if component_type.lower() == "plant component pump variablespeed":
            component_type = "Plant Component Pump:VariableSpeed"
        if component_type.lower() == "plant component chiller electric eir":
            component_type = "Plant Component Chiller:Electric:EIR"

        control_type = actuator_config.DESCRIPTOR.EnumValueName(
            "ControlType", actuator_config.actuated_component_control_type
        )
        control_type = " ".join(control_type.split("_"))

        # here we must use "on/off" instead of "on off" as stated by EnergyPlus :)
        if control_type.lower() == "on off supervisory":
            control_type = "on/off supervisory"

        initial_value = (
            actuator_config.initial_value if actuator_config.initial_value else None
        )
        self.epm.ExternalInterface_Actuator.add(
            name=name,
            actuated_component_unique_name=actuated_component_unique_name,
            actuated_component_type=component_type,
            actuated_component_control_type=control_type,
            optional_initial_value=initial_value,
        )

    def _set_observation(self, output_variable_config: EPlusObservationConfig) -> None:
        """
        Set Eplus Output:Variable using the input dict
        """
        # check whether the configuration contains all necessary ingredients

        if (
            output_variable_config.output_variable_config.key_value.lower()
            not in set.union(self.valid_key_values, "*")
        ):
            raise ValueError(
                f"Key value : {output_variable_config.output_variable_config.key_value} "
                f"is not a valid key name."
            )

        # check if the external schedule is already exist in the idf file
        match_func = (
            lambda x: x.key_value
            == output_variable_config.output_variable_config.key_value.lower()
            and x.variable_name
            == output_variable_config.output_variable_config.variable_name.lower()
        )
        if len(self.epm.Output_Variable.select(match_func)) > 0:
            out = self.epm.Output_Variable.select(match_func)
            out.delete()

        # add output variable
        self.epm.Output_Variable.add(
            key_value=output_variable_config.output_variable_config.key_value,
            variable_name=output_variable_config.output_variable_config.variable_name,
            reporting_frequency=output_variable_config.output_variable_config.reporting_frequency,
        )

    """-------------------------------Internal Util Function API----------------------------------------"""

    def _compute_cpu_power(
        self,
        utilization: Union[float, np.ndarray],
        inlet_temperature: Union[float, np.ndarray, Symbol],
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute CPU power with utilization and server inlet temperature
        Args:
            utilization:
            inlet_temperature:
        """
        if inlet_temperature is None:
            inlet_temperature = 0
        factor = self._fun_power_as_load_temp(utilization, inlet_temperature, name)
        cpu_power = self.design_cpu_power[name] * factor
        return cpu_power

    def _compute_fan_power(
        self,
        utilization: Union[float, np.ndarray],
        inlet_temperature: Union[float, np.ndarray, Symbol],
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute fan power with utilization and server inlet temperature
        Args:
            utilization:
            inlet_temperature:
        """
        if inlet_temperature is None:
            inlet_temperature = 0
        flow_frac = self._fun_flow_as_load_temp(utilization, inlet_temperature, name)
        fan_power = self.design_fan_power[name] * self._fun_power_as_flow(
            flow_frac, name
        )
        return fan_power

    def _compute_ups_power(
        self,
        cpu_power: np.ndarray,
        fan_power: np.ndarray,
        name: str,
    ) -> np.ndarray:
        """
        Compute UPS power with Partial Load Ratio (PLR)
        Args:
            cpu_power:
            fan_power:
        """
        partial_load_ratio = (cpu_power + fan_power) / (
            self.design_cpu_power[name] + self.design_fan_power[name]
        )
        ups_power = (cpu_power + fan_power) * (
            1
            - self.ups_efficiency[name]
            * self._fun_ups_efficiency_as_partial_load(partial_load_ratio, name)
        )
        return ups_power

    """----------------------------------------------Public API -----------------------------------------------------"""

    def batch_set_actions(self, action_configs: List[EPlusActionConfig]) -> None:
        for action_config in action_configs:
            config_type = action_config.WhichOneof("IDFConfig")
            if config_type == "schedule_config":
                self._set_external_schedule(action_config)
            else:
                self._set_external_actuator(action_config)

    def batch_set_observations(
        self, observation_configs: List[EPlusObservationConfig]
    ) -> None:
        for observation_config in observation_configs:
            if (
                observation_config.DESCRIPTOR.EnumValueName(
                    "ObservationType", observation_config.observation_type
                )
                != "EXTERNAL"
            ):
                self._set_observation(observation_config)

    def batch_set_inlet_temperature_schedule(
        self, env_config: EPlusEnvConfig
    ) -> Optional[List[EPlusActionConfig]]:
        schedules = []
        for ite in self.zone_ite_equipments:
            if ite.air_flow_calculation_method == "flowcontrolwithapproachtemperatures":
                config = EPlusActionConfig()
                config.variable_name = f"{ite.name} inlet temperature schedule"
                config.schedule_config.lb = env_config.inlet_temp_lb
                config.schedule_config.ub = env_config.inlet_temp_ub
                config.schedule_config.initial_value = env_config.inlet_temp_init
                config.schedule_config.scheduled_ite_equipment_name = ite.name
                config.schedule_config.schedule_type = 1
                self._set_external_schedule(config)
                schedules.append(config)
        return schedules if len(schedules) > 0 else None

    def batch_set_return_temperature_schedule(
        self, env_config: EPlusEnvConfig
    ) -> Optional[List[EPlusActionConfig]]:
        schedules = []
        for ite in self.zone_ite_equipments:
            if ite.air_flow_calculation_method == "flowcontrolwithapproachtemperatures":
                config = EPlusActionConfig()
                config.variable_name = f"{ite.name} return temperature schedule"
                config.schedule_config.lb = env_config.return_temp_lb
                config.schedule_config.ub = env_config.return_temp_ub
                config.schedule_config.initial_value = env_config.return_temp_init
                config.schedule_config.scheduled_ite_equipment_name = ite.name
                config.schedule_config.schedule_type = 2
                self._set_external_schedule(config)
                schedules.append(config)
        return schedules if len(schedules) > 0 else None

    def set_external_interface(self) -> None:
        try:
            self.epm.ExternalInterface.one()
        except RecordDoesNotExistError:
            self.epm.ExternalInterface.add(name_of_external_interface="ptolemyserver")

    def set_simulation_time(self, simulation_time_config: SimulationTimeConfig) -> None:
        """
        Set simulation time info for a simulation (i.e., time step interval, start month, ...)
        """
        run_periods = self.epm.RunPeriod.one()
        run_periods.begin_month = simulation_time_config.begin_month
        run_periods.begin_day_of_month = simulation_time_config.begin_day_of_month
        run_periods.end_month = simulation_time_config.end_month
        run_periods.end_day_of_month = simulation_time_config.end_day_of_month
        time_step = self.epm.Timestep.one()
        time_step.number_of_timesteps_per_hour = (
            simulation_time_config.number_of_timesteps_per_hour
        )

    def compute_server_power(
        self,
        utilization: Union[float, np.ndarray],
        inlet_temperature: Optional[Union[float, np.ndarray, Symbol]],
        name: str,
    ) -> np.ndarray:
        """
        Compute power consumption for each server
        """
        cpu_power = self._compute_cpu_power(utilization, inlet_temperature, name)
        fan_power = self._compute_fan_power(utilization, inlet_temperature, name)
        ups_power = self._compute_ups_power(cpu_power, fan_power, name)
        server_power = cpu_power + fan_power + ups_power
        return server_power

    def compute_server_flow_rate(
        self,
        utilization: Union[float, np.ndarray],
        inlet_temperature: Optional[Union[float, np.ndarray]],
        name: str,
    ) -> np.ndarray:
        """
        Compute air flow rate for each server
        """
        if inlet_temperature is None:
            inlet_temperature = 0
        flow_frac = self._fun_flow_as_load_temp(utilization, inlet_temperature, name)
        server_flow_rates = self.design_air_volumetric_flow_rate[name] * flow_frac
        return server_flow_rates

    def compute_server_outlet_temperature(
        self,
        utilization: Union[float, np.ndarray],
        inlet_temperature: float,
        server_flow_rate: float,
        name: str,
    ) -> Union[float, np.ndarray]:
        """
        Compute outlet temperature for each server
        """
        cpu_power = self._compute_cpu_power(utilization, inlet_temperature, name)
        fan_power = self._compute_fan_power(utilization, inlet_temperature, name)
        q_air = np.sum(cpu_power + fan_power)
        outlet_temperature = inlet_temperature + q_air / (
            self.air_cp * self.air_density * server_flow_rate
        )
        return outlet_temperature

    def save(self, save_path) -> None:
        """
        Save the EPM object into a new .idf file
        """
        self.epm.to_idf(save_path)

    @staticmethod
    def save_cfg_xml(
        observation_configs: List[EPlusObservationConfig],
        action_configs: List[EPlusActionConfig],
        schedule_configs: List[EPlusActionConfig] = None,
        save_path: Union[Path, str] = None,
    ) -> None:
        """
        Create an XML Element Tree that specifies all Eplus external interface variables (ExternalInterface:Schedule,
        ExternalInterface:Actuator, Output:Variable) and then save to the disk
        """
        root = ET.Element("BCVTB-variables")

        # add Eplus output variables
        for observation_config in observation_configs:
            if (
                observation_config.DESCRIPTOR.EnumValueName(
                    "ObservationType", observation_config.observation_type
                )
                != "EXTERNAL"
            ):
                variable_child = ET.SubElement(root, "variable")
                variable_child.attrib["source"] = "EnergyPlus"
                eplus_child = ET.SubElement(variable_child, "EnergyPlus")
                eplus_child.attrib[
                    "name"
                ] = observation_config.output_variable_config.key_value
                eplus_child.attrib[
                    "type"
                ] = observation_config.output_variable_config.variable_name

        # add BCVTB input schedules
        for action in action_configs:
            variable_child = ET.SubElement(root, "variable")
            variable_child.attrib["source"] = "Ptolemy"
            eplus_child = ET.SubElement(variable_child, "EnergyPlus")
            action_type = action.WhichOneof("IDFConfig")
            if action_type == "schedule_config":
                eplus_child.attrib["schedule"] = action.variable_name.lower()
            else:
                eplus_child.attrib["actuator"] = action.variable_name.lower()

        if schedule_configs is not None:
            for schedule in schedule_configs:
                logger.info(f'add internal "{schedule.variable_name}" schedule config')
                variable_child = ET.SubElement(root, "variable")
                variable_child.attrib["source"] = "Ptolemy"
                eplus_child = ET.SubElement(variable_child, "EnergyPlus")
                eplus_child.attrib["schedule"] = schedule.variable_name.lower()
        else:
            logger.info("no internal schedule config added")

        # create XML file
        tree = ET.ElementTree(root)
        ET.indent(tree, space="\t", level=0)
        with open(save_path, "wb") as f:
            # add necessary prefix
            f.write(
                '<?xml version="1.0" encoding="ISO-8859-1"?>\n'.encode("ISO-8859-1")
            )
            f.write(
                '<!DOCTYPE BCVTB-variables SYSTEM "variables.dtd">\n'.encode(
                    "ISO-8859-1"
                )
            )
            tree.write(f)
