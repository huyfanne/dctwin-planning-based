"""
This file implements the make functions for the chiller plant system. Each make functions are used to create the corresponding
HVAC system components in the EnergyPlus model. The make functions are called by the manager in the idf_builder.py file.
To add a new HVAC system component, you need to add a new make function here and make it callable in the manager.
"""


from eppy.modeleditor import IDF
from eppy.bunch_subclass import EpBunch

from dclib.cooling.plant.facilities import Chiller, Pump, Pipe, CoolingTower, HeatExchanger
from dclib.cooling.plant.loops import SizingPlant
from dclib.cooling.room.facilities.acu import ACU

from .utlis import fill_info, fill_inlet_outlet


def make_plant_sizing(model: IDF, plant_loop_name: str, sizing_plant: SizingPlant):
    """
    Make the plant sizing object in the model.
    :param model:
    :param plant_loop_name:
    :param sizing_plant:
    :return:
    """
    obj = model.newidfobject("Sizing:Plant".upper())
    obj["Plant_or_Condenser_Loop_Name"] = plant_loop_name
    fill_info(
        idf_obj_name="Sizing:Plant",
        idf_obj=obj,
        idd_infos=model.idd_info,
        filled_field=["AirLoop_Name"],
        config=sizing_plant,
    )


def make_pipe(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    pipe: Pipe,
    **kwargs,
) -> EpBunch:
    """
    Make the pipe object in the model. Now only support adiabatic pipe.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param pipe:
    :param kwargs:
    :return:
    """
    obj = model.newidfobject("Pipe:Adiabatic".upper(), Name=pipe.uid.lower())
    if pipe.uid.lower() == "":
        raise ValueError("Pipe name cannot be empty")
    obj = fill_inlet_outlet(
        branch_component_idx=branch_component_idx,
        obj=obj,
        branch=branch,
        name=pipe.uid.lower(),
        inlet_key_name="Inlet_Node_Name",
        outlet_key_name="Outlet_Node_Name",
    )
    return obj


def make_pump(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    pump: Pump,
    **kwargs,
) -> EpBunch:
    """
    Make the pump object in the model. Now only support variable speed pump.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param pump_name:
    :param pump:
    :param kwargs:
    :return:
    """
    obj: EpBunch = model.newidfobject(
        "Pump:VariableSpeed".upper(), Name=pump.uid.lower()
    )
    obj = fill_inlet_outlet(
        branch_component_idx=branch_component_idx,
        obj=obj,
        branch=branch,
        name=pump.uid.lower(),
        inlet_key_name="Inlet_Node_Name",
        outlet_key_name="Outlet_Node_Name",
    )

    """Fill in cooling model parameters"""
    obj["Design_Maximum_Flow_Rate"] = pump.cooling.design_maximum_flow_rate
    obj["Design_Pump_Head"] = pump.cooling.design_pump_head
    obj["Skin_Loss_Radiative_Fraction"] = pump.cooling.skin_loss_radiative_fraction
    obj["Impeller_Diameter"] = pump.cooling.impeller_diameter
    obj[
        "Design_Minimum_Flow_Rate_Fraction"
    ] = pump.cooling.design_minimum_flow_rate_fraction

    """Fill in power model parameters"""
    obj["Pump_Curve_Name"] = pump.power.pump_curve_name
    obj["Design_Power_Sizing_Method"] = pump.power.design_power_sizing_method
    obj[
        "Design_Electric_Power_per_Unit_Flow_Rate"
    ] = pump.power.design_electric_power_per_unit_flow_rate
    obj[
        "Design_Shaft_Power_per_Unit_Flow_Rate_per_Unit_Head"
    ] = pump.power.design_shaft_power_per_unit_flow_rate_per_unit_head
    obj["Design_Power_Consumption"] = pump.power.design_power_consumption
    obj["Motor_Efficiency"] = pump.power.motor_efficiency
    obj[
        "Fraction_of_Motor_Inefficiencies_to_Fluid_Stream"
    ] = pump.power.fraction_of_motor_inefficiencies_to_fluid_stream
    obj[
        "Coefficient_1_of_the_Part_Load_Performance_Curve"
    ] = pump.power.coefficient_1_of_the_part_load_performance_curve
    obj[
        "Coefficient_2_of_the_Part_Load_Performance_Curve"
    ] = pump.power.coefficient_2_of_the_part_load_performance_curve
    obj[
        "Coefficient_3_of_the_Part_Load_Performance_Curve"
    ] = pump.power.coefficient_3_of_the_part_load_performance_curve
    obj[
        "Coefficient_4_of_the_Part_Load_Performance_Curve"
    ] = pump.power.coefficient_4_of_the_part_load_performance_curve

    """Fill in control model parameters"""
    obj["Pump_Control_Type"] = pump.control.pump_control_type
    obj["Pump_Flow_Rate_Schedule_Name"] = pump.control.pump_flow_rate_schedule_name
    obj["VFD_Control_Type"] = pump.control.vfd_control_type
    obj["Pump_RPM_Schedule_Name"] = pump.control.pump_rpm_schedule_name
    obj["Minimum_Pressure_Schedule"] = pump.control.minimum_pressure_schedule
    obj["Maximum_Pressure_Schedule"] = pump.control.maximum_pressure_schedule
    obj["Minimum_RPM_Schedule"] = pump.control.minimum_rpm_schedule
    obj["Maximum_RPM_Schedule"] = pump.control.maximum_rpm_schedule

    return obj


def get_cooling_coil(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    acu: ACU,
    **kwargs,
) -> EpBunch:
    """
    Make a cooling coil object in the model. Now only supports water cooling coil.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param cooling_coil_name:
    :param cooling_coil:
    :return:
    """
    obj = model.getobject(
        "coil:cooling:water".upper(), f"{acu.uid.lower()} cooling coil"
    )
    assert (
        obj is not None
    ), f"Cannot find the cooling coil object: {acu.uid.lower()} cooling coil"
    obj = fill_inlet_outlet(
        obj=obj,
        branch=branch,
        name=f"{acu.uid.lower()} water",
        branch_component_idx=branch_component_idx,
        inlet_key_name="Water_Inlet_Node_Name",
        outlet_key_name="Water_Outlet_Node_Name",
    )
    coil_controller = model.getobject(
        "Controller:WaterCoil".upper(), f"{acu.uid.lower()} controller"
    )
    coil_controller["Actuator_Node_Name"] = obj["Water_Inlet_Node_Name"]
    return obj


def make_chiller(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    chiller: Chiller,
    **kwargs,
) -> EpBunch:
    """
    Make the chiller object in the model. Now only support Electric:EIR chiller.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param chiller:
    :param kwargs:
    :return:
    """
    if kwargs["type_"] == "chilled" and kwargs["side"] == "supply":
        obj = model.newidfobject(
            "chiller:electric:eir".upper(), Name=chiller.uid.lower()
        )
        obj = fill_inlet_outlet(
            branch_component_idx=branch_component_idx,
            obj=obj,
            branch=branch,
            name=f"{chiller.uid.lower()} chilled water",
            inlet_key_name="Chilled_Water_Inlet_Node_Name",
            outlet_key_name="Chilled_Water_Outlet_Node_Name",
        )
        obj["Reference_Capacity"] = chiller.cooling.reference_capacity
        obj["Reference_COP"] = chiller.cooling.reference_cop
        obj[
            "Reference_Leaving_Chilled_Water_Temperature"
        ] = chiller.cooling.reference_leaving_chilled_water_temperature
        obj[
            "Reference_Entering_Condenser_Fluid_Temperature"
        ] = chiller.cooling.reference_entering_condenser_fluid_temperature
        obj[
            "Reference_Chilled_Water_Flow_Rate"
        ] = chiller.cooling.reference_chilled_water_flow_rate
        obj[
            "Reference_Condenser_Fluid_Flow_Rate"
        ] = chiller.cooling.reference_condenser_fluid_flow_rate
        obj["Optimum_Part_Load_Ratio"] = chiller.cooling.optimum_part_load_ratio
        obj["Minimum_Part_Load_Ratio"] = chiller.cooling.minimum_part_load_ratio
        obj["Maximum_Part_Load_Ratio"] = chiller.cooling.maximum_part_load_ratio
        obj["Minimum_Unloading_Ratio"] = chiller.cooling.minimum_unloading_ratio
        obj["Heat_Recovery_Inlet_Node_Name"] = ""  # no heat recovery by default
        obj["Heat_Recovery_Outlet_Node_Name"] = ""
        obj[
            "Leaving_Chilled_Water_Lower_Temperature_Limit"
        ] = chiller.cooling.leaving_chilled_water_lower_temperature_limit
        obj["Chiller_Flow_Mode"] = chiller.cooling.chiller_flow_mode
        obj["Condenser_Type"] = chiller.cooling.condenser_type
        obj["Sizing_Factor"] = chiller.cooling.sizing_factor
        obj["Basin_Heater_Capacity"] = chiller.cooling.basin_heater_capacity
        obj[
            "Basin_Heater_Setpoint_Temperature"
        ] = chiller.cooling.basin_heater_setpoint_temperature
        obj[
            "Design_Heat_Recovery_Water_Flow_Rate"
        ] = chiller.cooling.design_heat_recovery_water_flow_rate
        obj["EndUse_Subcategory"] = "General"

        # Add performance curves for the chiller
        obj[
            "Cooling_Capacity_Function_of_Temperature_Curve_Name"
        ] = f"{chiller.uid.lower()} cooling capacity function of temperature curve"
        model.newidfobject(
            key="Curve:Biquadratic".upper(),
            Name=obj["Cooling_Capacity_Function_of_Temperature_Curve_Name"],
            Coefficient1_Constant=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                0
            ],
            Coefficient2_x=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                1
            ],
            Coefficient3_x2=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                2
            ],
            Coefficient4_y=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                3
            ],
            Coefficient5_y2=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                4
            ],
            Coefficient6_xy=chiller.cooling.cooling_capacity_function_of_temperature_curve[
                5
            ],
            Minimum_Value_of_x=0,
            Maximum_Value_of_x=100,
            Minimum_Value_of_y=0,
            Maximum_Value_of_y=100,
        )
        obj[
            "Electric_Input_to_Cooling_Output_Ratio_Function_of_Temperature_Curve_Name"
        ] = f"{chiller.uid.lower()} electric input to cooling output ratio function of temperature curve"
        model.newidfobject(
            key="Curve:Biquadratic".upper(),
            Name=obj[
                "Electric_Input_to_Cooling_Output_Ratio_Function_of_Temperature_Curve_Name"
            ],
            Coefficient1_Constant=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                0
            ],
            Coefficient2_x=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                1
            ],
            Coefficient3_x2=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                2
            ],
            Coefficient4_y=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                3
            ],
            Coefficient5_y2=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                4
            ],
            Coefficient6_xy=chiller.power.electric_input_to_cooling_output_ratio_function_of_temperature_curve[
                5
            ],
            Minimum_Value_of_x=0,
            Maximum_Value_of_x=100,
            Minimum_Value_of_y=0,
            Maximum_Value_of_y=100,
        )
        obj[
            "Electric_Input_to_Cooling_Output_Ratio_Function_of_Part_Load_Ratio_Curve_Name"
        ] = f"{chiller.uid.lower()} electric input to cooling output ratio function of part load ratio curve"
        model.newidfobject(
            key="Curve:Quadratic".upper(),
            Name=obj[
                "Electric_Input_to_Cooling_Output_Ratio_Function_of_Part_Load_Ratio_Curve_Name"
            ],
            Coefficient1_Constant=chiller.power.electric_input_to_cooling_output_ratio_function_of_part_load_ratio_curve[
                0
            ],
            Coefficient2_x=chiller.power.electric_input_to_cooling_output_ratio_function_of_part_load_ratio_curve[
                1
            ],
            Coefficient3_x2=chiller.power.electric_input_to_cooling_output_ratio_function_of_part_load_ratio_curve[
                2
            ],
            Minimum_Value_of_x=0,
            Maximum_Value_of_x=1,
        )
    elif kwargs["type_"] == "condenser" and kwargs["side"] == "demand":
        obj = model.getobject("chiller:electric:eir".upper(), chiller.uid.lower())
        obj = fill_inlet_outlet(
            branch_component_idx=branch_component_idx,
            obj=obj,
            branch=branch,
            name=f"{chiller.uid.lower()} condenser water",
            inlet_key_name="Condenser_Inlet_Node_Name",
            outlet_key_name="Condenser_Outlet_Node_Name",
        )
    else:
        raise ValueError("Invalid chiller type or side")
    return obj


def make_heat_exchanger(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    hx: HeatExchanger,
    **kwargs,
) -> EpBunch:
    """
    Make the fluid-to-fluid heat exchanger object in the model.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param hx:
    :param kwargs:
    :return:
    """
    if kwargs["type_"] == "chilled" and kwargs["side"] == "supply":
        obj = model.newidfobject("HeatExchanger:FluidToFluid".upper(), Name=hx.uid.lower())
        obj["Availability_Schedule_Name"] = "ALWAYS ON"
        obj = fill_inlet_outlet(
            branch_component_idx=branch_component_idx,
            obj=obj,
            branch=branch,
            name=f"{hx.uid.lower()} chilled water",
            inlet_key_name="Loop_Supply_Side_Inlet_Node_Name",
            outlet_key_name="Loop_Supply_Side_Outlet_Node_Name",
        )
        obj["Loop_Demand_Side_Design_Flow_Rate"] = hx.cooling.loop_demand_side_design_flow_rate
        obj["Loop_Supply_Side_Design_Flow_Rate"] = hx.cooling.loop_supply_side_design_flow_rate
        obj["Heat_Exchange_Model_Type"] = hx.cooling.heat_exchanger_model_type
        obj["Heat_Exchanger_UFactor_Times_Area_Value"] =\
            hx.cooling.heat_exchanger_u_factor_times_area_value
        obj["Control_Type"] = hx.cooling.control_type
        obj["Minimum_Temperature_Difference_to_Activate_Heat_Exchanger"] =\
            hx.cooling.minimum_temperature_difference_to_activate_heat_exchanger
        obj["Heat_Transfer_Metering_End_Use_Type"] = hx.cooling.heat_transfer_metering_end_use_type
        obj["Component_Override_Cooling_Control_Temperature_Mode"] =\
            hx.cooling.component_override_cooling_control_temperature_mode
        obj["Sizing_Factor"] = hx.cooling.sizing_factor
        obj["Operation_Minimum_Temperature_Limit"] = hx.cooling.operation_minimum_temperature_limit
        obj["Operation_Maximum_Temperature_Limit"] = hx.cooling.operation_maximum_temperature_limit

    elif kwargs["type_"] == "condenser" and kwargs["side"] == "demand":
        obj = model.getobject("HeatExchanger:FluidToFluid".upper(), hx.uid.lower())
        obj = fill_inlet_outlet(
            branch_component_idx=branch_component_idx,
            obj=obj,
            branch=branch,
            name=f"{hx.uid.lower()} condenser water",
            inlet_key_name="Loop_Demand_Side_Inlet_Node_Name",
            outlet_key_name="Loop_Demand_Side_Outlet_Node_Name",
        )
    else:
        raise ValueError("Invalid chiller type or side")
    return obj


def make_cooling_tower(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    cooling_tower: CoolingTower,
    **kwargs,
) -> EpBunch:
    """
    Make a cooling tower object in the model. Now only supports variable speed cooling towers.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param cooling_tower_name:
    :param cooling_tower:
    :param kwargs:
    :return:
    """
    obj = model.newidfobject(
        "coolingtower:variablespeed".upper(), Name=cooling_tower.uid.lower()
    )
    fill_inlet_outlet(
        branch_component_idx=branch_component_idx,
        obj=obj,
        branch=branch,
        name=cooling_tower.uid.lower(),
        inlet_key_name="Water_Inlet_Node_Name",
        outlet_key_name="Water_Outlet_Node_Name",
    )
    fill_info(
        idf_obj_name="CoolingTower:VariableSpeed",
        idf_obj=obj,
        idd_infos=model.idd_info,
        filled_field=["Water_Inlet_Node_Name", "Water_Outlet_Node_Name"],
        config=cooling_tower,
    )
    obj["Basin_Heater_Capacity"] = cooling_tower.cooling.basin_heater_capacity
    obj[
        "Basin_Heater_Operating_Schedule_Name"
    ] = cooling_tower.cooling.basin_heater_operating_schedule_name
    obj[
        "Basin_Heater_Setpoint_Temperature"
    ] = cooling_tower.cooling.basin_heater_setpoint_temperature
    obj["Blowdown_Calculation_Mode"] = cooling_tower.cooling.blowdown_calculation_mode
    obj[
        "Blowdown_Concentration_Ratio"
    ] = cooling_tower.cooling.blowdown_concentration_ratio
    obj[
        "Blowdown_Makeup_Water_Usage_Schedule_Name"
    ] = cooling_tower.cooling.blowdown_makeup_water_usage_schedule_name

    obj["Number_of_Cells"] = cooling_tower.cooling.number_of_cells
    obj["Cell_Control"] = cooling_tower.cooling.cell_control
    obj[
        "Cell_Minimum_Water_Flow_Rate_Fraction"
    ] = cooling_tower.cooling.cell_minimum_water_flow_rate_fraction
    obj[
        "Cell_Maximum_Water_Flow_Rate_Fraction"
    ] = cooling_tower.cooling.cell_maximum_water_flow_rate_fraction

    obj["Design_Air_Flow_Rate"] = cooling_tower.cooling.design_air_flow_rate
    obj[
        "Design_Approach_Temperature"
    ] = cooling_tower.cooling.design_approach_temperature
    obj[
        "Design_Inlet_Air_WetBulb_Temperature"
    ] = cooling_tower.cooling.design_inlet_air_wet_bulb_temperature
    obj["Design_Range_Temperature"] = cooling_tower.cooling.design_range_temperature
    obj["Design_Water_Flow_Rate"] = cooling_tower.cooling.design_water_flow_rate
    obj[
        "Minimum_Air_Flow_Rate_Ratio"
    ] = cooling_tower.cooling.minimum_air_flow_rate_ratio

    obj["Evaporation_Loss_Factor"] = cooling_tower.cooling.evaporation_loss_factor
    obj["Evaporation_Loss_Mode"] = cooling_tower.cooling.evaporation_loss_mode
    obj[
        "Fraction_of_Tower_Capacity_in_Free_Convection_Regime"
    ] = cooling_tower.cooling.fraction_of_tower_capacity_in_free_convection_regime
    obj["Supply_Water_Storage_Tank_Name"] = ""
    obj["Outdoor_Air_Inlet_Node_Name"] = ""

    """Fill in power-related parameters"""
    obj["Design_Fan_Power"] = cooling_tower.power.design_fan_power
    obj[
        "Fan_Power_Ratio_Function_of_Air_Flow_Rate_Ratio_Curve_Name"
    ] = f"{cooling_tower.uid.lower()} fan power ratio function of air flow rate ratio curve"
    model.newidfobject(
        key="Curve:Cubic".upper(),
        Name=obj["Fan_Power_Ratio_Function_of_Air_Flow_Rate_Ratio_Curve_Name"],
        Coefficient1_Constant=cooling_tower.power.fan_power_ratio_function_of_air_flow_rate_ratio_curve[
            0
        ],
        Coefficient2_x=cooling_tower.power.fan_power_ratio_function_of_air_flow_rate_ratio_curve[
            1
        ],
        Coefficient3_x2=cooling_tower.power.fan_power_ratio_function_of_air_flow_rate_ratio_curve[
            2
        ],
        Coefficient4_x3=cooling_tower.power.fan_power_ratio_function_of_air_flow_rate_ratio_curve[
            3
        ],
        Minimum_Value_of_x=0,
        Maximum_Value_of_x=1,
    )
    return obj
