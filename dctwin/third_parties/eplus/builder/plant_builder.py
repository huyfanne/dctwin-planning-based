from typing import Dict
from loguru import logger

from eppy.modeleditor import IDF

from dclib.cooling.plant.loops import (
    ChilledWaterLoops,
    CondenserWaterLoops,
    SecondaryChilledWaterLoops,
    Branch,
    MetaPlant,
)
from dclib.cooling.plant.plant import Plant

from .utils import (
    make_chiller,
    make_pipe,
    make_cooling_tower,
    make_thermal_storage_tank,
    make_plant_sizing,
    make_pump,
    get_cooling_coil,
    make_heat_exchanger
)


class PlantBuilder:
    """
    This class is used to build HVAC system for a building in EnergyPlus. It takes charge of the following tasks:
    1. Create air loops
    2. Create plant loops (chilled water, condensing water, etc.) and connect them to air loops. The plant loops are not
    mandatory for a building. If the input file does not specify any plant loops, the building will be simulated without
    plant loops. In this case, the DX cooling units are expected to be appeared in the air loops.
    """

    def __init__(self, model: IDF):
        self.model = model

    def _make_branch(
        self,
        loop,
        branch_name,
        branch_definition: Branch,
        type_: str = "chilled",
        side: str = "supply",
    ):
        branch = self.model.newidfobject("BRANCH", Name=branch_name)
        component_idx = 1
        # add pipe
        if branch_definition.components.pipes is not None:
            for pipe_name, pipe in branch_definition.components.pipes.items():
                eplus_obj = make_pipe(
                    self.model,
                    branch,
                    component_idx,
                    pipe,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = pipe.uid.lower()
                component_idx += 1
        # add thermal storage tanks
        if branch_definition.components.tanks is not None:
            for tank_name, tank in branch_definition.components.tanks.items():
                eplus_obj = make_thermal_storage_tank(
                    self.model,
                    branch,
                    component_idx,
                    tank,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = tank.uid.lower()
                component_idx += 1
        # add pump
        if branch_definition.components.pumps is not None:
            for pump_name, pump in branch_definition.components.pumps.items():
                eplus_obj = make_pump(
                    self.model,
                    branch,
                    component_idx,
                    pump,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = pump.uid.lower()
                component_idx += 1
        # add heat exchangers
        if branch_definition.components.heat_exchangers is not None:
            for hx_name, hx in branch_definition.components.heat_exchangers.items():
                eplus_obj = make_heat_exchanger(
                    self.model,
                    branch,
                    component_idx,
                    hx,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = hx.uid.lower()
                component_idx += 1
        # add chillers
        if branch_definition.components.chillers is not None:
            for chiller_name, chiller in branch_definition.components.chillers.items():
                eplus_obj = make_chiller(
                    self.model,
                    branch,
                    component_idx,
                    chiller,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = chiller.uid.lower()
                component_idx += 1
        # add cooling towers
        if branch_definition.components.cooling_towers is not None:
            for cooling_tower_name, cooling_tower in branch_definition.components.cooling_towers.items():
                eplus_obj = make_cooling_tower(
                    self.model,
                    branch,
                    component_idx,
                    cooling_tower,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = cooling_tower.uid.lower()
                component_idx += 1
        # set cooling coil branch
        if branch_definition.components.acu is not None:
            for acu_name, acu in branch_definition.components.acu.items():
                eplus_obj = get_cooling_coil(
                    self.model,
                    branch,
                    component_idx,
                    acu,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
                branch[f"Component_{component_idx}_Object_Type"] = eplus_obj.key
                branch[f"Component_{component_idx}_Name"] = f"{acu.uid.lower()} cooling coil"
                component_idx += 1
        return branch

    def _make_branches(
        self,
        loop,
        branch_definitions: Dict[str, Branch],
        type_: str = "plant",
        side: str = "supply",
    ):
        branches = []
        for branch_name, branch_definition in branch_definitions.items():
            branches.append(
                self._make_branch(
                    branch_name=branch_name,
                    branch_definition=branch_definition,
                    type_=type_,
                    side=side,
                    loop=loop,
                )
            )
        return branches

    def _init_plant_loop(self, loop_name, meta: MetaPlant):
        plant_loop = self.model.newidfobject("PlantLoop", Name=loop_name)
        plant_loop["Plant_Side_Inlet_Node_Name"] = f"{loop_name} supply inlet node"
        plant_loop["Plant_Side_Outlet_Node_Name"] = f"{loop_name} supply outlet node"
        plant_loop["Plant_Side_Branch_List_Name"] = f"{loop_name} supply branches"
        plant_loop["Plant_Side_Connector_List_Name"] = f"{loop_name} supply connectors"
        plant_loop["Demand_Side_Inlet_Node_Name"] = f"{loop_name} demand inlet node"
        plant_loop["Demand_Side_Outlet_Node_Name"] = f"{loop_name} demand outlet node"
        plant_loop["Demand_Side_Branch_List_Name"] = f"{loop_name} demand branches"
        plant_loop["Demand_Side_Connector_List_Name"] = f"{loop_name} demand connectors"
        plant_loop["Maximum_Loop_Temperature"] = 100
        plant_loop["Minimum_Loop_Temperature"] = 5
        plant_loop["Maximum_Loop_Flow_Rate"] = "autosize"
        plant_loop["Minimum_Loop_Flow_Rate"] = 0
        plant_loop[
            "Loop_Temperature_Setpoint_Node_Name"
        ] = f"{loop_name} supply outlet node"
        plant_loop["Loop_Circulation_Time"] = 0
        plant_loop["Load_Distribution_Scheme"] = meta.load_distribution_scheme
        plant_loop[
            "Plant_Loop_Demand_Calculation_Scheme"
        ] = meta.plant_loop_demand_calculation_scheme
        plant_loop["Common_Pipe_Simulation"] = meta.common_pipe_simulation
        return plant_loop

    def _make_branch_list(self, plant_loop, branches: list[Dict], side: str):
        if side == "supply":
            branch_list = self.model.newidfobject(
                "BRANCHLIST", Name=plant_loop.Plant_Side_Branch_List_Name
            )
            for branch in branches:
                branch_list.obj.append(branch["Name"])
        elif side == "demand":
            branch_list = self.model.newidfobject(
                "BRANCHLIST", Name=plant_loop.Demand_Side_Branch_List_Name
            )
            for branch in branches:
                branch_list.obj.append(branch["Name"])
        else:
            raise ValueError(f"side must be either 'supply' or 'demand', not {side}")
        return branch_list

    def _rename_loop_endpoint_node_names(
        self, plant_loop, branches: list[Dict], side: str
    ):
        if side == "supply":
            branches[0]["Component_1_Inlet_Node_Name"] = plant_loop[
                "Plant_Side_Inlet_Node_Name"
            ]
            branches[-1]["Component_1_Outlet_Node_Name"] = plant_loop[
                "Plant_Side_Outlet_Node_Name"
            ]
            component = self.model.getobject(
                branches[0]["Component_1_Object_Type"], branches[0]["Component_1_Name"]
            )
            component["Inlet_Node_Name"] = plant_loop["Plant_Side_Inlet_Node_Name"]
            component = self.model.getobject(
                branches[-1]["Component_1_Object_Type"],
                branches[-1]["Component_1_Name"],
            )
            component.Outlet_Node_Name = plant_loop["Plant_Side_Outlet_Node_Name"]
        elif side == "demand":
            branches[0]["Component_1_Inlet_Node_Name"] = plant_loop[
                "Demand_Side_Inlet_Node_Name"
            ]
            branches[-1]["Component_1_Outlet_Node_Name"] = plant_loop[
                "Demand_Side_Outlet_Node_Name"
            ]
            component = self.model.getobject(
                branches[0]["Component_1_Object_Type"], branches[0]["Component_1_Name"]
            )
            component.Inlet_Node_Name = plant_loop["Demand_Side_Inlet_Node_Name"]
            component = self.model.getobject(
                branches[-1]["Component_1_Object_Type"],
                branches[-1]["Component_1_Name"],
            )
            component.Outlet_Node_Name = plant_loop["Demand_Side_Outlet_Node_Name"]
        else:
            raise ValueError(f"side must be either 'supply' or 'demand', not {side}")

    def _make_plant_connector_list(
        self, plant_loop, branches, loop_name: str, side: str
    ):
        if side == "supply":
            connector_list = self.model.newidfobject(
                "CONNECTORLIST", Name=plant_loop.Plant_Side_Connector_List_Name
            )
        elif side == "demand":
            connector_list = self.model.newidfobject(
                "CONNECTORLIST", Name=plant_loop.Demand_Side_Connector_List_Name
            )
        else:
            raise ValueError(f"side must be either 'supply' or 'demand', not {side}")

        connector_list.Connector_1_Object_Type = "Connector:Splitter"
        connector_list.Connector_1_Name = f"{loop_name} {side} splitter"
        connector_list.Connector_2_Object_Type = "Connector:Mixer"
        connector_list.Connector_2_Name = f"{loop_name} {side} mixer"

        # make supply-side splitters and mixers
        splitter = self.model.newidfobject(
            "CONNECTOR:SPLITTER", Name=connector_list.Connector_1_Name
        )
        splitter["Inlet_Branch_Name"] = branches[0]["Name"]
        for idx, branch in enumerate(branches[1:-1]):
            splitter[f"Outlet_Branch_{idx + 1}_Name"] = branch["Name"]
        mixer = self.model.newidfobject(
            "CONNECTOR:MIXER", Name=connector_list.Connector_2_Name
        )
        mixer["Outlet_Branch_Name"] = branches[-1]["Name"]
        for idx, branch in enumerate(branches[1:-1]):
            mixer[f"Inlet_Branch_{idx + 1}_Name"] = branch["Name"]

    def _make_plant_loop(
        self,
        loop_name: str,
        meta: MetaPlant,
        supply_loop_branches: Dict[str, Branch],
        demand_loop_branches: Dict[str, Branch],
        type_: str = "chilled",
    ):
        assert type_ in ["chilled", "condenser", "secondary"],  logger.info(f"Making {type_} water loop: {loop_name}")
        plant_loop = self._init_plant_loop(loop_name, meta)

        # make branches for all supply branches in the plant loop
        supply_branches = self._make_branches(
            loop=plant_loop,
            branch_definitions=supply_loop_branches,
            type_=type_,
            side="supply",
        )
        self._make_branch_list(plant_loop, supply_branches, side="supply")
        self._rename_loop_endpoint_node_names(
            plant_loop, supply_branches, side="supply"
        )

        # make branches for all demand branches in the plant loop
        demand_branches = self._make_branches(
            loop=plant_loop,
            branch_definitions=demand_loop_branches,
            type_=type_,
            side="demand",
        )
        self._make_branch_list(plant_loop, demand_branches, side="demand")
        self._rename_loop_endpoint_node_names(
            plant_loop, demand_branches, side="demand"
        )

        # make supply side and demand side connector list
        self._make_plant_connector_list(
            plant_loop, supply_branches, loop_name, side="supply"
        )
        self._make_plant_connector_list(
            plant_loop, demand_branches, loop_name, side="demand"
        )

        # fill in the plant operation scheme and plant equipment list
        plant_operation_schemes = self.model.newidfobject(
            key="PlantEquipmentOperationSchemes".upper(),
        )
        plant_loop[
            "Plant_Equipment_Operation_Scheme_Name"
        ] = f"{loop_name} operation scheme"
        plant_operation_schemes["Name"] = f"{loop_name} operation scheme"
        plant_operation_schemes[
            "Control_Scheme_1_Object_Type"
        ] = "PlantEquipmentOperation:CoolingLoad"
        plant_operation_schemes[
            "Control_Scheme_1_Name"
        ] = f"{loop_name} cooling operation scheme"
        plant_operation_schemes["Control_Scheme_1_Schedule_Name"] = f"Always On".upper()

        plant_operation_scheme = self.model.newidfobject(
            key="PlantEquipmentOperation:CoolingLoad".upper(),
            Name=f"{loop_name} cooling operation scheme",
        )
        plant_operation_scheme["Load_Range_1_Lower_Limit"] = 0
        plant_operation_scheme["Load_Range_1_Upper_Limit"] = 1000000000
        plant_operation_scheme[
            "Range_1_Equipment_List_Name"
        ] = f"{loop_name} equipment list"

        plant_equipment_list = self.model.newidfobject(
            key="PlantEquipmentList".upper(), Name=f"{loop_name} equipment list"
        )
        idx = 1
        if type_ == "chilled":
            for branch_name, branch in supply_loop_branches.items():
                if branch.side == "middle":
                    for component_type, components in branch.components:
                        if component_type == "chillers" and components is not None:
                            for component_name, component in components.items():
                                plant_equipment_list[
                                    f"Equipment_{idx}_Object_Type"
                                ] = "Chiller:Electric:EIR"
                                plant_equipment_list[
                                    f"Equipment_{idx}_Name"
                                ] = component.uid.lower()
                                idx += 1
        elif type_ == "secondary":
            for branch_name, branch in supply_loop_branches.items():
                if branch.side == "middle":
                    for component_type, components in branch.components:
                        if component_type == "tanks" and components is not None:
                            for component_name, component in components.items():
                                plant_equipment_list[
                                    f"Equipment_{idx}_Object_Type"
                                ] = "Thermalstorage:Chilledwater:Mixed"
                                plant_equipment_list[
                                    f"Equipment_{idx}_Name"
                                ] = component.uid.lower()
                                idx += 1
        else:
            for branch_name, branch in supply_loop_branches.items():
                if branch.side == "middle":
                    for component_type, components in branch.components:
                        if component_type == "cooling_towers":
                            for component_name, component in components.items():
                                plant_equipment_list[
                                    f"Equipment_{idx}_Object_Type"
                                ] = "CoolingTower:VariableSpeed"
                                plant_equipment_list[
                                    f"Equipment_{idx}_Name"
                                ] = component.uid.lower()
                                idx += 1

    def _make_chilled_water_loops(
        self, chilled_water_loops: Dict[str, ChilledWaterLoops]
    ):
        for loop_name, chilled_water_loop in chilled_water_loops.items():
            self._make_plant_loop(
                loop_name=loop_name,
                meta=chilled_water_loop.meta,
                supply_loop_branches=chilled_water_loop.supply_branches,
                demand_loop_branches=chilled_water_loop.demand_branches,
                type_="chilled",
            )
            make_plant_sizing(self.model, loop_name, chilled_water_loop.sizing)
            # Add plant loop exit temperature set point manager to control the plant loop exit temperature as
            # the design loop exit temperature
            if chilled_water_loop.meta.setpoint_manager:
                self.model.newidfobject(
                    key="SetpointManager:Scheduled".upper(),
                    Name=f"{loop_name} exit temperature setpoint manager",
                    Control_Variable="Temperature",
                    Schedule_Name=f"{loop_name} exit temperature setpoint schedule",
                    Setpoint_Node_or_NodeList_Name=f"{loop_name} supply outlet node",
                )
                self.model.newidfobject(
                    key="Schedule:Constant".upper(),
                    Name=f"{loop_name} exit temperature setpoint schedule",
                    Schedule_Type_Limits_Name="Temperature",
                    Hourly_Value=chilled_water_loop.sizing.design_loop_exit_temperature,
                )
            for branch_name, branch in chilled_water_loop.supply_branches.items():
                if branch.side == "middle":
                    if branch.components.heat_exchangers is not None:
                        for hx_name, hx in branch.components.heat_exchangers.items():
                            obj = self.model.getobject(
                                key="HeatExchanger:FluidToFluid".upper(),
                                name=hx_name
                            )
                            obj["Heat_Exchanger_Setpoint_Node_Name"] = obj["Loop_Supply_Side_Outlet_Node_Name"]
                            self.model.newidfobject(
                                key="SetpointManager:FollowSystemNodeTemperature".upper(),
                                Name=f"{obj['Name']} setpoint manager",
                                Control_Variable="Temperature",
                                Reference_Node_Name=f"{loop_name} supply outlet node",
                                Reference_Temperature_Type="NodeDryBulb",
                                Offset_Temperature_Difference=0.0,
                                Maximum_Limit_Setpoint_Temperature=chilled_water_loop.meta.maximum_setpoint_temperature,
                                Minimum_Limit_Setpoint_Temperature=chilled_water_loop.meta.minimum_setpoint_temperature,
                                Setpoint_Node_or_NodeList_Name=obj["Heat_Exchanger_Setpoint_Node_Name"]
                            )

    def _make_condenser_loops(self, condenser_loops: Dict[str, CondenserWaterLoops]):
        for loop_name, condenser_loop in condenser_loops.items():
            self._make_plant_loop(
                loop_name=loop_name,
                meta=condenser_loop.meta,
                supply_loop_branches=condenser_loop.supply_branches,
                demand_loop_branches=condenser_loop.demand_branches,
                type_="condenser",
            )
            make_plant_sizing(self.model, loop_name, condenser_loop.sizing)
            # Add condenser loop exit temperature set point manager to control the condenser loop exit temperature.
            # Two types of set point managers are supported: scheduled and follow outdoor air temperature.
            if condenser_loop.meta.setpoint_manager:
                self.model.newidfobject(
                    key="SetpointManager:Scheduled".upper(),
                    Name=f"{loop_name} exit temperature setpoint manager",
                    Control_Variable="Temperature",
                    Schedule_Name=f"{loop_name} exit temperature setpoint",
                    Setpoint_Node_or_NodeList_Name=f"{loop_name} supply outlet node"
                )
                self.model.newidfobject(
                    key="Schedule:Constant".upper(),
                    Name=f"{loop_name} exit temperature setpoint",
                    Schedule_Type_Limits_Name="Temperature",
                    Hourly_Value=condenser_loop.sizing.design_loop_exit_temperature
                )
            else:
                self.model.newidfobject(
                    key="SetpointManager:FollowOutdoorAirTemperature".upper(),
                    Name=f"{loop_name} setpoint manager",
                    Control_Variable="Temperature",
                    Reference_Temperature_Type="OutdoorAirWetBulb",
                    Offset_Temperature_Difference=condenser_loop.meta.offset_temperature_difference,
                    Maximum_Setpoint_Temperature=condenser_loop.meta.maximum_setpoint_temperature,
                    Minimum_Setpoint_Temperature=condenser_loop.meta.minimum_setpoint_temperature,
                    Setpoint_Node_or_NodeList_Name=f"{loop_name} supply outlet node"
                )

    def _make_secondary_loops(self, secondary_loops: Dict[str, SecondaryChilledWaterLoops]):
        if secondary_loops is None:
            return
        for loop_name, secondary_loop in secondary_loops.items():
            self._make_plant_loop(
                loop_name=loop_name,
                meta=secondary_loop.meta,
                supply_loop_branches=secondary_loop.supply_branches,
                demand_loop_branches=secondary_loop.demand_branches,
                type_="secondary",
            )
            make_plant_sizing(self.model, loop_name, secondary_loop.sizing)
            # Add plant loop exit temperature set point manager to control the plant loop exit temperature as
            # the design loop exit temperature
            if secondary_loop.meta.setpoint_manager:
                self.model.newidfobject(
                    key="SetpointManager:Scheduled".upper(),
                    Name=f"{loop_name} exit temperature setpoint manager",
                    Control_Variable="Temperature",
                    Schedule_Name=f"{loop_name} exit temperature setpoint schedule",
                    Setpoint_Node_or_NodeList_Name=f"{loop_name} supply outlet node",
                )
                self.model.newidfobject(
                    key="Schedule:Constant".upper(),
                    Name=f"{loop_name} exit temperature setpoint schedule",
                    Schedule_Type_Limits_Name="Temperature",
                    Hourly_Value=secondary_loop.sizing.design_loop_exit_temperature,
                )
            for branch_name, branch in secondary_loop.supply_branches.items():
                if branch.side == "middle":
                    if branch.components.tanks is not None:
                        for tank_name in branch.components.tanks:
                            obj = self.model.getobject(
                                key="THERMALSTORAGE:CHILLEDWATER:MIXED".upper(),
                                name=tank_name
                            )
                            obj["Setpoint_Temperature_Schedule_Name"] =\
                                f"{loop_name} exit temperature setpoint schedule"

    def make_plant(self, plant: Plant):
        """
        Make the HVAC system loops from the plant configuration file. We first make the air loops, then the chilled
        water loops, then the condenser water loops.
        :param plant:
        :return:
        """
        # build chiller plant system loops according to the configuration file
        self._make_secondary_loops(plant.secondary_chilled_water_loops)
        self._make_chilled_water_loops(plant.chilled_water_loops)
        self._make_condenser_loops(plant.condenser_water_loops)
