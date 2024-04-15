from typing import Dict

from dclib.models.geometry import Geometry
from eppy.modeleditor import IDF
from eppy.bunch_subclass import EpBunch

from dclib.cooling.room.facilities.acu import ACU, ACUOutdoorAir
from dclib.cooling.room.sizing import SizingSystem
from dclib.construction.surfaces import Surface
from dclib.cooling.room.facilities.duct import Duct
from dclib.room import RoomGeometry

from .utlis import fill_info, fill_inlet_outlet


def make_system_sizing(
    model: IDF,
    air_loop_name: str,
    sizing_system: SizingSystem,
) -> None:
    """
    Make the system sizing object in the model.
    :param model:
    :param air_loop_name:
    :param sizing_system:
    :return: None
    """
    obj = model.newidfobject("Sizing:System".upper())
    obj["AirLoop_Name"] = air_loop_name
    fill_info(
        idf_obj_name="Sizing:System",
        idf_obj=obj,
        idd_infos=model.idd_info,
        filled_field=["AirLoop_Name"],
        config=sizing_system,
    )
    # fill in special fields
    obj["100_Outdoor_Air_in_Cooling"] = sizing_system.outdoor_air_in_cooling_100
    obj["100_Outdoor_Air_in_Heating"] = sizing_system.outdoor_air_in_heating_100


def make_duct(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    duct_name: str,
    duct: Duct,
    **kwargs,
) -> EpBunch:
    """
    Make the duct object in the model. Now only support adiabatic duct.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param duct_name:
    :param duct:
    :param kwargs:
    :return: EpBunch
    """
    obj = model.newidfobject("Duct".upper(), Name=duct_name)
    obj = fill_inlet_outlet(
        branch_component_idx=branch_component_idx,
        obj=obj,
        branch=branch,
        name=duct_name,
        inlet_key_name="Inlet_Node_Name",
        outlet_key_name="Outlet_Node_Name",
    )
    obj, _ = fill_info(
        idf_obj_name="Duct",
        idf_obj=obj,
        idd_infos=model.idd_info,
        filled_field=["Inlet_Node_Name", "Outlet_Node_Name"],
        config=duct,
    )
    return obj


def make_cooling_coil(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    cooling_coil_name: str,
    acu: ACU,
    **kwargs,
) -> EpBunch:
    """
    Make a cooling coil object in the model. Now only supports water cooling coil.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param cooling_coil_name:
    :param acu: ACU object that this cooling coil belongs to
    :param kwargs:
    :return: EpBunch
    """
    obj = model.newidfobject("coil:cooling:water".upper(), Name=cooling_coil_name)
    obj["Availability_Schedule_Name"] = f"Always On".upper()
    if branch_component_idx > 1:
        obj["Air_Inlet_Node_Name"] = branch[
            f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
        ]
        obj["Air_Outlet_Node_Name"] = f"{cooling_coil_name} air outlet node"
        branch[f"Component_{branch_component_idx}_Inlet_Node_Name"] = branch[
            f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
        ]
        branch[f"Component_{branch_component_idx}_Outlet_Node_Name"] = obj[
            "Air_Outlet_Node_Name"
        ]
    else:
        obj["Air_Inlet_Node_Name"] = branch[
            f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
        ]
        obj["Air_Inlet_Node_Name"] = f"{cooling_coil_name} air inlet node"
        obj["Air_Outlet_Node_Name"] = f"{cooling_coil_name} air outlet node"
        branch["Component_1_Inlet_Node_Name"] = obj["Air_Inlet_Node_Name"]
        branch[f"Component_1_Outlet_Node_Name"] = obj["Air_Outlet_Node_Name"]
    # fill in info
    obj["Design_Air_Flow_Rate"] = acu.cooling.design_air_flow_rate
    obj["Design_Inlet_Air_Humidity_Ratio"] = acu.cooling.design_inlet_air_humidity_ratio
    obj[
        "Design_Outlet_Air_Humidity_Ratio"
    ] = acu.cooling.design_outlet_air_humidity_ratio
    obj["Design_Inlet_Air_Temperature"] = acu.cooling.design_inlet_air_temperature
    obj["Design_Outlet_Air_Temperature"] = acu.cooling.design_outlet_air_temperature
    obj["Design_Water_Flow_Rate"] = acu.cooling.design_water_flow_rate
    obj["Design_Inlet_Water_Temperature"] = acu.cooling.design_inlet_water_temperature
    obj[
        "Design_Water_Temperature_Difference"
    ] = acu.cooling.design_water_temperature_difference
    obj["Heat_Exchanger_Configuration"] = acu.cooling.heat_exchanger_configuration
    return obj


def make_fan(
    model: IDF,
    branch: EpBunch,
    branch_component_idx,
    fan_name: str,
    acu: ACU,
    **kwargs,
) -> EpBunch:
    """
    Make a fan object in the model. Now only supports variable volume fan.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param fan_name:
    :param acu: ACU object that this fan belongs to
    :param kwargs:
    :return:
    """
    obj = model.newidfobject("fan:variablevolume".upper(), Name=fan_name)
    obj["Availability_Schedule_Name"] = f"Always On".upper()
    loop = kwargs["loop"]
    obj["Air_Inlet_Node_Name"] = branch[
        f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
    ]
    obj["Air_Outlet_Node_Name"] = loop["Supply_Side_Outlet_Node_Names"]
    branch[f"Component_{branch_component_idx}_Inlet_Node_Name"] = branch[
        f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
    ]
    branch[f"Component_{branch_component_idx}_Outlet_Node_Name"] = obj[
        "Air_Outlet_Node_Name"
    ]
    branch[
        f"Component_{branch_component_idx}_Object_Type"
    ] = "Fan:VariableVolume".upper()
    branch[f"Component_{branch_component_idx}_Name"] = fan_name

    obj["Fan_Power_Coefficient_1"] = acu.power.fan_power_coefficient_1
    obj["Fan_Power_Coefficient_2"] = acu.power.fan_power_coefficient_2
    obj["Fan_Power_Coefficient_3"] = acu.power.fan_power_coefficient_3
    obj["Fan_Power_Coefficient_4"] = acu.power.fan_power_coefficient_4
    obj["Fan_Power_Coefficient_5"] = acu.power.fan_power_coefficient_5
    obj["Fan_Power_Minimum_Air_Flow_Rate"] = acu.power.fan_power_minimum_air_flow_rate
    obj["Fan_Power_Minimum_Flow_Fraction"] = acu.power.fan_power_minimum_flow_fraction
    obj[
        "Fan_Power_Minimum_Flow_Rate_Input_Method"
    ] = acu.power.fan_power_minimum_flow_rate_input_method
    obj["Fan_Total_Efficiency"] = acu.power.fan_total_efficiency
    obj["Motor_Efficiency"] = acu.power.motor_efficiency
    obj["Maximum_Flow_Rate"] = acu.cooling.maximum_flow_rate
    obj["Pressure_Rise"] = acu.cooling.pressure_rise
    obj["Motor_In_Airstream_Fraction"] = acu.power.motor_in_airstream_fraction
    return obj


def make_oa_equipment_list(
    model: IDF,
    oa_name: str,
    air_loop: EpBunch
) -> EpBunch:
    """
    Make an outdoor air equipment list and its components in the model.
    :param model:
    :param oa_name: outdoor air system name
    :param air_loop: air loop object
    :return:
    """
    obj = model.newidfobject(
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList".upper(),
        Name=f"{oa_name} outdoor air equipment",
    )
    obj["Component_1_Object_Type"] = "OutdoorAir:Mixer".upper()
    obj["Component_1_Name"] = f"{oa_name} mixer box"
    mixer = model.newidfobject("OutdoorAir:Mixer".upper(), Name=f"{oa_name} mixer box")
    mixer["Mixed_Air_Node_Name"] = f"{oa_name} mixed air node"
    mixer["Relief_Air_Stream_Node_Name"] = f"{oa_name} relief air outlet node"
    mixer["Outdoor_Air_Stream_Node_Name"] = f"{oa_name} outside air inlet node"
    outdoor_node_list = model.newidfobject("OutdoorAir:NodeList".upper())
    outdoor_node_list["Node_or_NodeList_Name_1"] = f"{oa_name} outside air inlet node"
    node_list = model.newidfobject(
        "NodeList".upper(), Name=f"{oa_name} outside air inlet nodes"
    )
    node_list["Node_1_Name"] = f"{oa_name} outside air inlet node"
    airloop = model.getobject("AirLoopHVAC".upper(), name=air_loop["Name"])
    mixer["Return_Air_Stream_Node_Name"] = airloop["Supply_Side_Inlet_Node_Name"]
    return obj


def make_oa_system(
    model: IDF,
    branch: EpBunch,
    oa: ACUOutdoorAir,
    air_loop: EpBunch = None,
) -> EpBunch:
    """
    Make an outdoor air system in the model.
    :param model:
    :param branch:
    :param branch_component_idx:
    :param oa: ACUOutdoorAir object
    :param air_loop: air loop object
    :return:
    """
    obj = model.newidfobject(
        "AirLoopHVAC:OutdoorAirSystem".upper(), Name=oa.uid.lower()
    )
    obj["Controller_List_Name"] = f"{oa.uid.lower()} controllers"
    obj["Outdoor_Air_Equipment_List_Name"] = f"{oa.uid.lower()} outdoor air equipment"
    obj["Availability_Manager_List_Name"] = f"{oa.uid.lower()} availability list"
    make_oa_equipment_list(model, oa.uid.lower(), air_loop)
    branch["Component_1_Object_Type"] = "AirLoopHVAC:OutdoorAirSystem".upper()
    branch["Component_1_Name"] = oa.uid.lower()
    branch["Component_1_Inlet_Node_Name"] = air_loop["Supply_Side_Inlet_Node_Name"]
    branch["Component_1_Outlet_Node_Name"] = f"{oa.uid.lower()} mixed air node"

    availability_manager = model.newidfobject(
        "AvailabilityManagerAssignmentList".upper(),
        Name=f"{oa.uid.lower()} availability manager list",
    )
    availability_manager[
        "Availability_Manager_1_Object_Type"
    ] = "AvailabilityManager:Scheduled"
    availability_manager[
        "Availability_Manager_1_Name"
    ] = f"{oa.uid.lower()} availability manager"
    model.newidfobject(
        "AvailabilityManager:Scheduled".upper(),
        Name=f"{oa.uid.lower()} availability manager",
        Schedule_Name="Always On".upper(),
    )
    obj[
        "Availability_Manager_List_Name"
    ] = f"{oa.uid.lower()} availability manager list"

    return obj


def make_surfaces(
    model: IDF,
    geometry_config: RoomGeometry | Geometry,
    surfaces_config: Dict[str, Surface],
) -> None:

    planes = geometry_config.plane
    height = geometry_config.height
    wall_idx, wall_idx_next = 0, 1

    for surface_name, surface_config in surfaces_config.items():
        surface = model.newidfobject(key="BuildingSurface:Detailed".upper())
        surface["Name"] = surface_name
        surface["Surface_Type"] = surface_config.type.value
        surface["Construction_Name"] = surface_config.construction_name
        surface["Zone_Name"] = surface_config.zone_name
        # "Ground" if surface_config.type.value == "Floor" else "Outdoors"
        surface[
            "Outside_Boundary_Condition"
        ] = surface_config.outside_boundary_condition.value
        surface[
            "Outside_Boundary_Condition_Object"
        ] = surface_config.outside_boundary_condition_object
        surface["Sun_Exposure"] = (
            "NoSun"
            if (
                surface_config.type.value == "Floor"
                or surface_config.type.value == "Ceiling"
            )
            else "SunExposed"
        )
        surface["Wind_Exposure"] = (
            "NoWind"
            if (
                surface_config.type.value == "Floor"
                or surface_config.type.value == "Ceiling"
            )
            else "WindExposed"
        )
        surface[
            "View_Factor_to_Ground"
        ] = surface_config.view_factor_to_ground  # to change?
        surface["Number_of_Vertices"] = surface_config.number_of_vertices

        if surface_config.type.value == "Wall":
            # only support surface with four vertex
            surface["Vertex_1_Xcoordinate"] = f"{planes[wall_idx].x}"
            surface["Vertex_1_Ycoordinate"] = f"{planes[wall_idx].y}"
            surface["Vertex_1_Zcoordinate"] = f"{planes[wall_idx].z + height}"
            surface["Vertex_2_Xcoordinate"] = f"{planes[wall_idx].x}"
            surface["Vertex_2_Ycoordinate"] = f"{planes[wall_idx].y}"
            surface["Vertex_2_Zcoordinate"] = f"{planes[wall_idx].z}"
            surface["Vertex_3_Xcoordinate"] = f"{planes[wall_idx_next].x}"
            surface["Vertex_3_Ycoordinate"] = f"{planes[wall_idx_next].y}"
            surface["Vertex_3_Zcoordinate"] = f"{planes[wall_idx_next].z}"
            surface["Vertex_4_Xcoordinate"] = f"{planes[wall_idx_next].x}"
            surface["Vertex_4_Ycoordinate"] = f"{planes[wall_idx_next].y}"
            surface["Vertex_4_Zcoordinate"] = f"{planes[wall_idx_next].z + height}"
            wall_idx += 1
            wall_idx_next = (wall_idx + 1) % len(planes)

        elif surface_config.type.value == "Floor":
            for idx in range(len(planes)):
                surface[f"Vertex_{idx + 1}_Xcoordinate"] = f"{planes[2-idx].x}"
                surface[f"Vertex_{idx + 1}_Ycoordinate"] = f"{planes[2-idx].y}"
                surface[f"Vertex_{idx + 1}_Zcoordinate"] = f"{planes[2-idx].z}"

        elif (
            surface_config.type.value == "Roof"
            or surface_config.type.value == "Ceiling"
        ):
            for idx in range(len(planes)):
                surface[f"Vertex_{idx + 1}_Xcoordinate"] = f"{planes[idx].x}"
                surface[f"Vertex_{idx + 1}_Ycoordinate"] = f"{planes[idx].y}"
                surface[f"Vertex_{idx + 1}_Zcoordinate"] = f"{planes[idx].z + height}"
