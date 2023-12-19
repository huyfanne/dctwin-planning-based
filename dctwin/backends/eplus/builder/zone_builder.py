from typing import Dict, OrderedDict

from eppy.bunch_subclass import EpBunch
from eppy.modeleditor import IDF

from dclib.ite.composite import ITE
from dclib.electrical.room.electrical_device import ElectricEquipment, Light, People
from dclib.room import Room, Thermostats
from dclib.cooling.room.facilities.acu import ACU, ACUOutdoorAir
from dclib.cooling.room.sizing import SizingZone, SizingSystem

from .utils import (
    make_surfaces,
    make_oa_system,
    make_fan,
    make_system_sizing,
    make_cooling_coil,
)

class RoomBuilder:

    def __init__(self, model: IDF):
        self.model = model

    def _make_room(self, room: Room):
        zone = self.model.newidfobject(
            key="Zone".upper()
        )
        zone["Name"] = room.uid.lower()
        zone["Part_of_Total_Floor_Area"] = ""
        make_surfaces(self.model, room.geometry, room.constructions.surfaces)

    def _make_ites(self, zone_name: str, ites: OrderedDict[str, ITE]):
        for ite_name, ite_config in ites.items():
            ite = self.model.newidfobject(key="ElectricEquipment:ITE:AirCooled".upper())
            ite["Name"] = ite_config.uid.lower()
            ite["Zone_Name"] = zone_name
            ite["Air_Flow_Calculation_Method"] = ite_config.air_flow_calculation_method
            ite["Design_Power_Input_Calculation_Method"] = ite_config.design_power_input_calculation_method
            ite["Watts_per_Unit"] = ite_config.watts_per_unit
            ite["Number_of_Units"] = ite_config.number_of_units
            ite["Watts_per_Zone_Floor_Area"] = ite_config.watts_per_zone_floor_area
            ite["Design_Power_Input_Schedule_Name"] = f"{ite_config.uid} operation schedule"
            ite["CPU_Loading_Schedule_Name"] = f"{ite_config.uid} cpu schedule"
            ite["Design_Fan_Power_Input_Fraction"] = ite_config.design_fan_power_input_fraction
            ite["Design_Fan_Air_Flow_Rate_per_Power_Input"] = ite_config.design_fan_air_flow_rate_per_power_input
            ite["Design_Entering_Air_Temperature"] = ite_config.design_entering_air_temperature
            ite["Environmental_Class"] = ite_config.environmental_class
            ite["Air_Inlet_Connection_Type"] = ite_config.air_inlet_connection_type
            ite["Air_Inlet_Room_Air_Model_Node_Name"] = ite_config.air_inlet_room_air_model_node_name
            ite["Air_Outlet_Room_Air_Model_Node_Name"] = ite_config.air_outlet_room_air_model_node_name
            ite["Supply_Air_Node_Name"] = ite_config.supply_air_node_name
            ite["Design_Recirculation_Fraction"] = ite_config.design_recirculation_fraction
            ite["Recirculation_Function_of_Loading_and_Supply_Temperature_Curve_Name"] = \
                f"{ite['Name']} recirculation function of loading and supply temperature curve"
            ite["Design_Electric_Power_Supply_Efficiency"] = ite_config.design_electric_power_supply_efficiency
            ite["Electric_Power_Supply_Efficiency_Function_of_Part_Load_Ratio_Curve_Name"] = \
                f"{ite['Name']} electric power supply efficiency function of part load ratio curve"
            ite[
                "Fraction_of_Electric_Power_Supply_Losses_to_Zone"
            ] = ite_config.fraction_of_electric_power_supply_losses_to_zone
            ite["CPU_EndUse_Subcategory"] = ite_config.cpu_enduse_subcategory
            ite["Fan_EndUse_Subcategory"] = ite_config.fan_enduse_subcategory
            ite["Electric_Power_Supply_EndUse_Subcategory"] = ite_config.electric_power_supply_enduse_subcategory

            # Add performance curves
            ite["CPU_Power_Input_Function_of_Loading_and_Air_Temperature_Curve_Name"] = \
                f"{ite['Name']} cpu power input function of loading and supply Temperature curve"
            ite["Air_Flow_Function_of_Loading_and_Air_Temperature_Curve_Name"] = \
                f"{ite['Name']} air flow function of loading and air temperature curve"
            ite["Fan_Power_Input_Function_of_Flow_Curve_Name"] = \
                f"{ite['Name']} fan power input function of flow curve"
            ite["Recirculation_Function_of_Loading_and_Supply_Temperature_Curve_Name"] = \
                f"{ite['Name']} recirculation function of loading and supply temperature curve"
            ite["Electric_Power_Supply_Efficiency_Function_of_Part_Load_Ratio_Curve_Name"] = \
                f"{ite['Name']} electric power supply efficiency function of part load ratio curve"
            self.model.newidfobject(
                key="Curve:BiQuadratic".upper(),
                Name=ite["CPU_Power_Input_Function_of_Loading_and_Air_Temperature_Curve_Name"],
                Coefficient1_Constant=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[0],
                Coefficient2_x=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[1],
                Coefficient3_x2=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[2],
                Coefficient4_y=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[3],
                Coefficient5_y2=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[4],
                Coefficient6_xy=ite_config.cpu_power_input_function_of_loading_and_air_temperature_curve[5],
                Minimum_Value_of_x=0,
                Maximum_Value_of_x=1.5,
                Minimum_Value_of_y=-10,
                Maximum_Value_of_y=99,
            )
            self.model.newidfobject(
                key="Curve:BiQuadratic".upper(),
                Name=ite["Air_Flow_Function_of_Loading_and_Air_Temperature_Curve_Name"],
                Coefficient1_Constant=ite_config.air_flow_function_of_loading_and_air_temperature_curve[0],
                Coefficient2_x=ite_config.air_flow_function_of_loading_and_air_temperature_curve[1],
                Coefficient3_x2=ite_config.air_flow_function_of_loading_and_air_temperature_curve[2],
                Coefficient4_y=ite_config.air_flow_function_of_loading_and_air_temperature_curve[3],
                Coefficient5_y2=ite_config.air_flow_function_of_loading_and_air_temperature_curve[4],
                Coefficient6_xy=ite_config.air_flow_function_of_loading_and_air_temperature_curve[5],
                Minimum_Value_of_x=0,
                Maximum_Value_of_x=1.5,
                Minimum_Value_of_y=-10,
                Maximum_Value_of_y=99,
            )
            self.model.newidfobject(
                key="Curve:Quadratic".upper(),
                Name=ite["Fan_Power_Input_Function_of_Flow_Curve_Name"],
                Coefficient1_Constant=ite_config.fan_power_input_function_of_flow_curve[0],
                Coefficient2_x=ite_config.fan_power_input_function_of_flow_curve[1],
                Coefficient3_x2=ite_config.fan_power_input_function_of_flow_curve[2],
                Minimum_Value_of_x=0,
                Maximum_Value_of_x=99,
            )
            self.model.newidfobject(
                key="Curve:BiQuadratic".upper(),
                Name=ite["Recirculation_Function_of_Loading_and_Supply_Temperature_Curve_Name"],
                Coefficient1_Constant=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[0],
                Coefficient2_x=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[1],
                Coefficient3_x2=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[2],
                Coefficient4_y=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[3],
                Coefficient5_y2=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[4],
                Coefficient6_xy=ite_config.recirculation_fraction_function_of_loading_and_air_temperature_curve[5],
                Minimum_Value_of_x=0,
                Maximum_Value_of_x=1.5,
                Minimum_Value_of_y=-10,
                Maximum_Value_of_y=99,
            )
            self.model.newidfobject(
                key="Curve:Quadratic".upper(),
                Name=ite["Electric_Power_Supply_Efficiency_Function_of_Part_Load_Ratio_Curve_Name"],
                Coefficient1_Constant=ite_config.electric_power_supply_efficiency_function_of_part_load_ratio_curve[0],
                Coefficient2_x=ite_config.electric_power_supply_efficiency_function_of_part_load_ratio_curve[1],
                Coefficient3_x2=ite_config.electric_power_supply_efficiency_function_of_part_load_ratio_curve[2],
                Minimum_Value_of_x=0,
                Maximum_Value_of_x=99,
            )
            self.model.newidfobject(
                key="Schedule:Constant".upper(),
                Name=f"{ite_config.uid} operation schedule",
                Schedule_Type_Limits_Name="Any Number",
                Hourly_Value=1,
            )
            self.model.newidfobject(
                key="Schedule:Constant".upper(),
                Name=f"{ite_config.uid} cpu schedule",
                Schedule_Type_Limits_Name="Any Number",
                Hourly_Value=1.0,
            )

    def _make_occupancy(self, zone_name: str, config: People):
        if config:
            occupancy = self.model.newidfobject(key="People".upper())
            occupancy["Name"] = config.name
            occupancy["Zone_or_ZoneList_Name"] = zone_name
            occupancy["Number_of_People"] = config.number_of_people

    def _make_electrical_equipment(self, zone_name: str, config: ElectricEquipment):
        if config:
            electrical_equipment = self.model.newidfobject(
                key="ElectricEquipment".upper()
            )
            electrical_equipment["Name"] = config.name
            electrical_equipment["Zone_or_ZoneList_Name"] = zone_name

    def _make_lightning(self, zone_name: str, config: Light):
        if config:
            light = self.model.newidfobject(key="Lights".upper())
            light["Name"] = config.name
            light["Zone_or_ZoneList_Name"] = zone_name
            light["Lighting_Level"] = config.lighting_power

    def _make_zone_sizing(self, zone_name: str, config: SizingZone):
        sizing = self.model.newidfobject(key="Sizing:Zone".upper())
        sizing["Zone_or_ZoneList_Name"] = zone_name
        sizing[
            "Zone_Cooling_Design_Supply_Air_Temperature_Input_Method"
        ] = config.zone_heating_design_supply_air_temperature_input_method
        sizing["Zone_Cooling_Design_Supply_Air_Temperature"] = config.zone_cooling_design_supply_air_temperature
        sizing[
            "Zone_Cooling_Design_Supply_Air_Temperature_Difference"
        ] = config.zone_cooling_design_supply_air_temperature_difference
        sizing[
            "Zone_Heating_Design_Supply_Air_Temperature_Input_Method"
        ] = config.zone_heating_design_supply_air_temperature_input_method
        sizing["Zone_Heating_Design_Supply_Air_Temperature"] = config.zone_heating_design_supply_air_temperature
        sizing[
            "Zone_Heating_Design_Supply_Air_Temperature_Difference"
        ] = config.zone_heating_design_supply_air_temperature_difference
        sizing["Zone_Cooling_Design_Supply_Air_Humidity_Ratio"] = config.zone_cooling_design_supply_air_humidity_ratio
        sizing[
            "Zone_Heating_Design_Supply_Air_Humidity_Ratio"
        ] = config.zone_heating_design_supply_air_humidity_ratio
        sizing["Design_Specification_Outdoor_Air_Object_Name"] = f"SZ DSOA {zone_name}"
        sizing[
            "Design_Specification_Zone_Air_Distribution_Object_Name"
        ] = config.design_specification_zone_air_distribution_object_name
        sizing["Zone_Heating_Sizing_Factor"] = config.zone_heating_sizing_factor
        sizing["Zone_Cooling_Sizing_Factor"] = config.zone_cooling_sizing_factor
        sizing["Cooling_Design_Air_Flow_Method"] = config.cooling_design_air_flow_method
        sizing["Cooling_Design_Air_Flow_Rate"] = config.cooling_design_air_flow_rate
        sizing["Cooling_Minimum_Air_Flow_per_Zone_Floor_Area"] = config.cooling_minimum_air_flow_per_zone_floor_area
        sizing["Cooling_Minimum_Air_Flow"] = config.cooling_minimum_air_flow
        sizing["Cooling_Minimum_Air_Flow_Fraction"] = config.cooling_minimum_air_flow_fraction
        sizing["Heating_Design_Air_Flow_Method"] = config.heating_design_air_flow_method
        sizing["Heating_Design_Air_Flow_Rate"] = config.heating_design_air_flow_rate
        sizing["Heating_Maximum_Air_Flow_per_Zone_Floor_Area"] = config.heating_maximum_air_flow_per_zone_floor_area
        sizing["Heating_Maximum_Air_Flow"] = config.heating_maximum_air_flow
        sizing["Heating_Maximum_Air_Flow_Fraction"] = config.heating_maximum_air_flow_fraction
        sizing[
            "Design_Specification_Zone_Air_Distribution_Object_Name"
        ] = config.design_specification_zone_air_distribution_object_name
        sizing["Account_for_Dedicated_Outdoor_Air_System"] = config.account_for_dedicated_outdoor_air_system
        sizing[
            "Dedicated_Outdoor_Air_System_Control_Strategy"
        ] = config.dedicated_outdoor_air_system_control_strategy
        sizing[
            "Dedicated_Outdoor_Air_Low_Setpoint_Temperature_for_Design"
        ] = config.dedicated_outdoor_air_low_setpoint_temperature_for_design
        sizing[
            "Dedicated_Outdoor_Air_High_Setpoint_Temperature_for_Design"
        ] = config.dedicated_outdoor_air_high_setpoint_temperature_for_design

        self.model.newidfobject(
            key="DesignSpecification:OutdoorAir".upper(),
            Name=sizing["Design_Specification_Outdoor_Air_Object_Name"],
            Outdoor_Air_Method=config.design_specification_outdoor_air_method,
            Outdoor_Air_Flow_per_Person=config.design_specification_outdoor_air_flow_per_person,
            Outdoor_Air_Flow_per_Zone_Floor_Area=config.design_specification_outdoor_air_flow_per_zone_floor_area,
            Outdoor_Air_Flow_per_Zone=config.design_specification_outdoor_air_flow_per_zone,
            Outdoor_Air_Flow_Air_Changes_per_Hour=config.design_specification_outdoor_air_flow_air_changes_per_hour
        )

    def _make_zone_thermostat(self, zone_name: str, config: Thermostats, acus: Dict[str, ACU]):
        num_acu = len(acus)
        if num_acu == 0:
            return
        thermostat = self.model.newidfobject(
            key="ThermostatSetpoint:DualSetpoint".upper()
        )
        thermostat["Name"] = f"{zone_name} thermostat"
        thermostat[
            "Heating_Setpoint_Temperature_Schedule_Name"
        ] = f"{zone_name} heating setpoint schedule"
        thermostat[
            "Cooling_Setpoint_Temperature_Schedule_Name"
        ] = f"{zone_name} cooling setpoint schedule"

        self.model.newidfobject(
            key="ZoneControl:Thermostat".upper(),
            Name=f"{zone_name} room temperature control",
            Zone_or_ZoneList_Name=zone_name,
            Control_Type_Schedule_Name=f"{zone_name} control type schedule",
            Control_1_Object_Type="ThermostatSetpoint:DualSetpoint",
            Control_1_Name=thermostat["Name"],
        )
        self.model.newidfobject(
            key="Schedule:Constant".upper(),
            Name=f"{zone_name} heating setpoint schedule",
            Schedule_Type_Limits_Name="Temperature",
            Hourly_Value=config.heating_setpoint,
        )
        self.model.newidfobject(
            key="Schedule:Constant".upper(),
            Name=f"{zone_name} cooling setpoint schedule",
            Schedule_Type_Limits_Name="Temperature",
            Hourly_Value=config.cooling_setpoint,
        )
        self.model.newidfobject(
            key="Schedule:Constant".upper(),
            Name=f"{zone_name} control type schedule",
            Schedule_Type_Limits_Name="Any Number",
            Hourly_Value=4,
        )  # 4 means dual setpoint thermostat

    def _init_air_loop(self, loop_name: str, sizing: SizingSystem):
        # create air loop object
        air_loop = self.model.newidfobject("AirLoopHVAC".upper(), Name=loop_name)
        air_loop["Design_Supply_Air_Flow_Rate"] = sizing.design_supply_air_flow_rate
        # name the nodes, connector, and branch list
        air_loop["Branch_List_Name"] = f"{loop_name} branches"
        # air_loop["Connector_List_Name"] = f"{loop_name} connectors"
        air_loop["Supply_Side_Inlet_Node_Name"] = f"{loop_name} supply inlet node"
        air_loop["Supply_Side_Outlet_Node_Names"] = f"{loop_name} supply outlet node"
        air_loop["Demand_Side_Inlet_Node_Names"] = f"{loop_name} demand inlet node"
        air_loop["Demand_Side_Outlet_Node_Name"] = f"{loop_name} demand outlet node"

        return air_loop

    def _make_oa_controller(self, oa, air_loop):
        controller_list = self.model.newidfobject(
            "AirLoopHVAC:ControllerList".upper(),
            Name=f"{oa['Name']} controllers",
        )
        controller_list["Controller_1_Object_Type"] = "Controller:OutdoorAir"
        controller_list["Controller_1_Name"] = f"{oa['Name']} controller"
        controller = self.model.newidfobject(key="Controller:OutdoorAir".upper())
        controller["Name"] = f"{oa['Name']} controller"
        controller["Relief_Air_Outlet_Node_Name"] = f"{oa['Name']} relief air outlet node"
        controller["Return_Air_Node_Name"] = air_loop["Supply_Side_Inlet_Node_Name"]
        controller["Mixed_Air_Node_Name"] = f"{oa['Name']} mixed air node"
        controller["Actuator_Node_Name"] = f"{oa['Name']} outside air inlet node"
        controller["Minimum_Outdoor_Air_Flow_Rate"] = "autosize"
        controller["Maximum_Outdoor_Air_Flow_Rate"] = "autosize"
        controller["Economizer_Control_Type"] = "FixedDryBulb"
        controller["Economizer_Maximum_Limit_DryBulb_Temperature"] = 23
        controller["Economizer_Maximum_Limit_Dewpoint_Temperature"] = 13.5
        controller["Economizer_Minimum_Limit_DryBulb_Temperature"] = -20
        controller["Lockout_Type"] = "NoLockout"
        controller["Minimum_Limit_Type"] = "FixedMinimum"
        controller["Minimum_Outdoor_Air_Schedule_Name"] = "OAFractionSched"
        return controller

    def _make_zone_hvac(self, zone_name: str, acus: Dict[str, ACU]) -> None:
        """
        Build the ZoneHVAC objects for a thermal zone
        :param zone_name:
        :param num_acu:
        :return:
        """
        num_acu = len(acus)
        if num_acu == 0:
            return
        self.model.newidfobject(
            key="ZoneHVAC:EquipmentConnections".upper(),
            Zone_Name=zone_name,
            Zone_Conditioning_Equipment_List_Name=f"{zone_name} equipment list",
            Zone_Air_Inlet_Node_or_NodeList_Name=f"{zone_name} inlets",
            Zone_Air_Node_Name=f"{zone_name} air node",
            Zone_Return_Air_Node_or_NodeList_Name=f"{zone_name} returns",
        )
        zone_inlets = self.model.newidfobject(
            key="NodeList".upper(),
            Name=f"{zone_name} inlets",
        )
        for i in range(num_acu):
            zone_inlets[f"Node_{i + 1}_Name"] = f"{zone_name} inlet node {i + 1}"
        zone_returns = self.model.newidfobject(
            key="NodeList".upper(),
            Name=f"{zone_name} returns",
        )
        for i in range(num_acu):
            zone_returns[f"Node_{i + 1}_Name"] = f"{zone_name} return node {i + 1}"
        zone_equipment_list = self.model.newidfobject(
            key="ZoneHVAC:EquipmentList".upper(),
            Name=f"{zone_name} equipment list",
            Load_Distribution_Scheme="UniformLoad",
        )
        for i in range(num_acu):
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Object_Type"] = "ZoneHVAC:AirDistributionUnit"
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Name"] = f"{zone_name} air distribution unit {i + 1}"
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Cooling_Sequence"] = i + 1
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Heating_or_NoLoad_Sequence"] = i + 1
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Sequential_Cooling_Fraction_Schedule_Name"] = ""
            zone_equipment_list[f"Zone_Equipment_{i + 1}_Sequential_Heating_Fraction_Schedule_Name"] = ""
        for i in range(num_acu):
            self.model.newidfobject(
                key="ZoneHVAC:AirDistributionUnit".upper(),
                Name=f"{zone_name} air distribution unit {i + 1}",
                Air_Distribution_Unit_Outlet_Node_Name=f"{zone_name} inlet node {i + 1}",
                Air_Terminal_Object_Type="AirTerminal:SingleDuct:VAV:NoReheat",
                Air_Terminal_Name=f"{zone_name} air terminal unit {i + 1}",
            )
            self.model.newidfobject(
                key="AirTerminal:SingleDuct:VAV:NoReheat".upper(),
                Name=f"{zone_name} air terminal unit {i + 1}",
                Availability_Schedule_Name="Always On".upper(),
                Air_Outlet_Node_Name=f"{zone_name} inlet node {i + 1}",
                Air_Inlet_Node_Name=f"{zone_name} air terminal unit {i + 1} inlet node",
                Maximum_Air_Flow_Rate="autosize",
                Zone_Minimum_Air_Flow_Input_Method="Constant",
                Constant_Minimum_Air_Flow_Fraction=0.0,
            )

    def _make_outdoor_air_system_and_controller(
        self,
        branch: EpBunch,
        oa: ACUOutdoorAir,
        air_loop: EpBunch,
    ):
        oa_eplus = make_oa_system(
            model=self.model,
            branch=branch,
            oa=oa,
            air_loop=air_loop,
        )
        self._make_oa_controller(oa_eplus, air_loop)
        self.model.newidfobject(
            "SetpointManager:MixedAir".upper(),
            Name=f"{oa_eplus['Name']} mixed air manager",
            Control_Variable="Temperature",
            Reference_Setpoint_Node_Name=air_loop["Supply_Side_Outlet_Node_Names"],
            Fan_Inlet_Node_Name=f"{oa_eplus['Name']} mixed air node",
            Fan_Outlet_Node_Name=air_loop["Supply_Side_Outlet_Node_Names"],
            Setpoint_Node_or_NodeList_Name=f"{oa_eplus['Name']} mixed air node"
        )

    def _make_acus(self, zone_name: str, acus: Dict[str, ACU], sizing: SizingSystem):
        for idx, (acu_name, acu) in enumerate(acus.items()):
            loop_name = f"{acu.uid.lower()} air loop"
            air_loop = self._init_air_loop(loop_name, sizing)
            self.model.newidfobject(
                key="BranchList".upper(),
                Name=air_loop["Branch_List_Name"],
                Branch_1_Name=f"{acu.uid.lower()} air loop main branch",
            )
            branch = self.model.newidfobject(
                key="Branch".upper(),
                Name=f"{acu.uid.lower()} air loop main branch",
            )
            if acu.cooling.oa is not None:
                self._make_outdoor_air_system_and_controller(
                    branch=branch,
                    oa=acu.cooling.oa,
                    air_loop=air_loop,
                )
            # create cooling coil
            branch_component_idx = 2 if acu.cooling.oa is not None else 1
            coil = make_cooling_coil(
                model=self.model,
                branch=branch,
                branch_component_idx=branch_component_idx,
                cooling_coil_name=f"{acu.uid.lower()} cooling coil",
                acu=acu,
                type_="air",
                loop=air_loop,
            )
            branch[f"Component_{branch_component_idx}_Object_Type"] = "Coil:Cooling:Water".upper()
            branch[f"Component_{branch_component_idx}_Name"] = f"{acu.uid.lower()} cooling coil"
            # create coil controller
            controller_list = self.model.newidfobject(
                "AirLoopHVAC:ControllerList".upper(),
                Name=f"{acu.uid.lower()} controllers",
                Controller_1_Object_Type="Controller:WaterCoil",
                Controller_1_Name=f"{acu.uid.lower()} controller",
            )
            air_loop["Controller_List_Name"] = controller_list["Name"]
            controller = self.model.newidfobject(key="Controller:WaterCoil".upper())
            controller["Name"] = f"{acu.uid.lower()} controller"
            controller["Control_Variable"] = acu.controller.control_variable
            controller["Action"] = "REVERSE"
            controller["Actuator_Variable"] = "FLOW"
            controller["Sensor_Node_Name"] = air_loop["Supply_Side_Outlet_Node_Names"]

            make_fan(
                model=self.model,
                branch=branch,
                branch_component_idx=3 if acu.cooling.oa is not None else 2,
                fan_name=f"{acu.uid.lower()} fan",
                acu=acu,
                loop=air_loop
            )

            # make air supply path
            zone_air_supply_path = self.model.newidfobject("AirLoopHVAC:SupplyPath".upper())
            zone_air_supply_path["Name"] = f"{loop_name} supply path"
            zone_air_supply_path["Supply_Air_Path_Inlet_Node_Name"] = air_loop["Demand_Side_Inlet_Node_Names"]
            zone_air_supply_path["Component_1_Object_Type"] = "AirLoopHVAC:ZoneSplitter"
            zone_air_supply_path["Component_1_Name"] = f"{loop_name} air splitter"
            zone_splitter = self.model.newidfobject("AirLoopHVAC:ZoneSplitter".upper())
            zone_splitter["Name"] = f"{loop_name} air splitter"
            zone_splitter["Inlet_Node_Name"] = air_loop["Demand_Side_Inlet_Node_Names"]
            zone_splitter[f"Outlet_1_Node_Name"] = f"{zone_name} air terminal unit {idx + 1} inlet node"

            # make air return path
            self.model.newidfobject(
                key="AirLoopHVAC:ReturnPath".upper(),
                Name=f"{loop_name} return path",
                Return_Air_Path_Outlet_Node_Name=air_loop["Demand_Side_Outlet_Node_Name"],
                Component_1_Object_Type="AirLoopHVAC:ZoneMixer",
                Component_1_Name=f"{loop_name} air mixer",
            )
            self.model.newidfobject(
                "AirLoopHVAC:ZoneMixer".upper(),
                Name=f"{loop_name} air mixer",
                Outlet_Node_Name=air_loop["Demand_Side_Outlet_Node_Name"],
                Inlet_1_Node_Name=f"{zone_name} return node {idx + 1}",
            )

            # make air loop availability manager
            air_loop["Availability_Manager_List_Name"] = f"{loop_name} availability manager list"
            availability_manager = self.model.newidfobject(
                "AvailabilityManagerAssignmentList".upper(),
                Name=f"{loop_name} availability manager list"
            )
            availability_manager["Availability_Manager_1_Object_Type"] = "AvailabilityManager:Scheduled"
            availability_manager["Availability_Manager_1_Name"] = f"{loop_name} availability manager"
            self.model.newidfobject(
                "AvailabilityManager:Scheduled".upper(),
                Name=f"{loop_name} availability manager",
                Schedule_Name="Always On".upper()
            )
            make_system_sizing(
                model=self.model,
                air_loop_name=air_loop["Name"],
                sizing_system=sizing,
            )
            # set up coil outlet air temperature setpoint manager (each coil should have one)
            if acu.controller:
                if (acu.controller.control_variable == "Temperature" or
                        acu.controller.control_variable == "TemperatureAndHumidityRatio"):
                    self.model.newidfobject(
                        key="SetpointManager:Scheduled",
                        Name=f"{loop_name} supply air temperature setpoint manager",
                        Control_Variable="Temperature",
                        Schedule_Name=f"{loop_name} supply air temperature schedule",
                        Setpoint_Node_or_NodeList_Name=air_loop["Supply_Side_Outlet_Node_Names"],
                    )
                    self.model.newidfobject(
                        key="Schedule:Constant".upper(),
                        Schedule_Type_Limits_Name="Any Number",
                        Name=f"{loop_name} supply air temperature schedule",
                        Hourly_Value=acu.controller.supply_air_temperature_setpoint,
                    )
                if (acu.controller.control_variable == "HumidityRatio" or
                        acu.controller.control_variable == "TemperatureAndHumidityRatio"):
                    self.model.newidfobject(
                        key="SetpointManager:Scheduled",
                        Name=f"{loop_name} supply air maximum humidity ratio setpoint manager",
                        Control_Variable="MaximumHumidityRatio",
                        Schedule_Name=f"{loop_name} supply air maximum humidity ratio schedule",
                        Setpoint_Node_or_NodeList_Name=air_loop["Supply_Side_Outlet_Node_Names"],
                    )
                    self.model.newidfobject(
                        key="Schedule:Constant".upper(),
                        Schedule_Type_Limits_Name="Any Number",
                        Name=f"{loop_name} supply air maximum humidity ratio schedule",
                        Hourly_Value=acu.controller.supply_air_maximum_humidity_ratio_setpoint,
                    )
                    self.model.newidfobject(
                        key="SetpointManager:Scheduled",
                        Name=f"{loop_name} supply air minimum humidity ratio setpoint manager",
                        Control_Variable="MinimumHumidityRatio",
                        Schedule_Name=f"{loop_name} supply air minimum humidity ratio schedule",
                        Setpoint_Node_or_NodeList_Name=air_loop["Supply_Side_Outlet_Node_Names"],
                    )
                    self.model.newidfobject(
                        key="Schedule:Constant".upper(),
                        Schedule_Type_Limits_Name="Any Number",
                        Name=f"{loop_name} supply air minimum humidity ratio schedule",
                        Hourly_Value=acu.controller.supply_air_minimum_humidity_ratio_setpoint,
                    )

    def _make_hvac(self, zone_name: str, acus: Dict[str, ACU], sizing: SizingSystem):
        self._make_zone_hvac(zone_name, acus)
        self._make_acus(zone_name, acus, sizing)

    def make_rooms(self, rooms: Dict[str, Room]):
        for room_name, config in rooms.items():
            self._make_room(config)
            self._make_hvac(room_name, config.constructions.acus, config.sizing.sizing_system)
            self._make_ites(room_name, config.constructions.heat_gains.ites)
            # self._make_occupancy(room_name, config.constructions.heat_gains.people)
            # self._make_lightning(room_name, config.constructions.heat_gains.light)
            # self._make_electrical_equipment(room_name, config.constructions.heat_gains.electric_equipment)
            self._make_zone_sizing(room_name, config.sizing.sizing_zone)
            self._make_zone_thermostat(room_name, config.thermostats, config.constructions.acus)