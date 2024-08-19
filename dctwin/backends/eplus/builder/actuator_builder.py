from typing import Dict, OrderedDict
from eppy.modeleditor import IDF
from dclib.cooling.plant.plant import Plant
from dclib.room import Room
from dctwin.utils.const import rho_air, air_specific_heat


class ActuatorBuilder:
    def __init__(self, model: IDF):
        self.model = model
        self.program_name_list = []

    def _make_actuators(self, plant: Plant, rooms: Dict[str, Room]):
        for _, chilled_water_loop in plant.chilled_water_loops.items():
            for _, branch in chilled_water_loop.supply_branches.items():
                # pump actuator
                if branch.components.pumps is not None:
                    for _, pump in branch.components.pumps.items():
                        if pump.operation.pump_mass_flow_rate is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=pump.uid,
                                actuated_component_type="Pump",
                                actuated_component_control_type="Pump Mass Flow Rate",
                                value=pump.operation.pump_mass_flow_rate,
                            )
                        if pump.operation.pump_pressure_rise is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=pump.uid,
                                actuated_component_type="Pump",
                                actuated_component_control_type="Pump Pressure Rise",
                                value=pump.operation.pump_pressure_rise,
                            )
                        if pump.operation.pump_maximum_mass_flow_rate is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=pump.uid,
                                actuated_component_type="Pump",
                                actuated_component_control_type="Pump Maximum Mass Flow Rate",
                                value=pump.operation.pump_maximum_mass_flow_rate,
                            )
                        if pump.operation.pump_on_off_supervisory is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=pump.uid,
                                actuated_component_type="Pump",
                                actuated_component_control_type="Pump On Off Supervisory",
                                value=pump.operation.pump_on_off_supervisory,
                            )

                # chiller actuator
                if branch.components.chillers is not None:
                    for _, chiller in branch.components.chillers.items():
                        if chiller.operation.on_off_supervisory is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=chiller.uid,
                                actuated_component_type="Plant Component Chiller:Electric:EIR",
                                actuated_component_control_type="On/Off Supervisory",
                                value=chiller.operation.on_off_supervisory,
                            )

        for _, condenser_water_loop in plant.condenser_water_loops.items():
            for _, branch in condenser_water_loop.supply_branches.items():
                # cooling tower actuator
                if branch.components.cooling_towers is not None:
                    for _, cooling_tower in branch.components.cooling_towers.items():
                        if cooling_tower.operation.on_off_supervisory is not None:
                            self._make_actuator_program(
                                actuated_component_unique_name=cooling_tower.uid,
                                actuated_component_type="Plant Component CoolingTower:VariableSpeed",
                                actuated_component_control_type="On/Off Supervisory",
                                value=cooling_tower.operation.on_off_supervisory,
                            )

        for _, room in rooms.items():
            for _, acu in room.constructions.acus.items():
                if acu.cooling.operating.supply_air_temperature is not None:
                    self._make_actuator_program(
                        actuated_component_unique_name=f"{acu.uid} AIR LOOP SUPPLY AIR TEMPERATURE SCHEDULE",
                        actuated_component_type="Schedule:Constant",
                        actuated_component_control_type="Schedule Value",
                        value=acu.cooling.operating.supply_air_temperature,
                    )
                if acu.cooling.operating.supply_air_volume_flow_rate is not None:
                    supply_air_mass_flow_rate = (
                        rho_air * acu.cooling.operating.supply_air_volume_flow_rate
                    )
                    self._make_actuator_program(
                        actuated_component_unique_name=f"{acu.uid} FAN",
                        actuated_component_type="Fan",
                        actuated_component_control_type="Fan Air Mass Flow Rate",
                        value=supply_air_mass_flow_rate,
                    )

        # program calling manager
        if len(self.program_name_list) > 0:
            program_calling_manager = self.model.newidfobject(
                "EnergyManagementSystem:ProgramCallingManager"
            )
            program_calling_manager["Name"] = f"internal_actuator_calling_manager"
            program_calling_manager[
                "EnergyPlus_Model_Calling_Point"
            ] = "InsideHVACSystemIterationLoop"
            for idx, program_name in enumerate(self.program_name_list):
                program_calling_manager[f"Program_Name_{idx+1}"] = program_name

    def _make_actuator_program(
        self,
        actuated_component_unique_name: str,
        actuated_component_type: str,
        actuated_component_control_type: str,
        value: float,
    ):
        actuator_name = (
            f"{actuated_component_unique_name} {actuated_component_control_type}".replace(
                "-", "_"
            )
            .replace(" ", "_")
            .replace("/", "_")
            .lower()
        )
        program_name = f"program_{actuator_name}"

        actuator = self.model.newidfobject(key="EnergyManagementSystem:Actuator")
        actuator["Name"] = actuator_name
        actuator["Actuated_Component_Unique_Name"] = actuated_component_unique_name
        actuator["Actuated_Component_Type"] = actuated_component_type
        actuator["Actuated_Component_Control_Type"] = actuated_component_control_type

        program = self.model.newidfobject(key="EnergyManagementSystem:Program")
        program["Name"] = program_name
        program["Program_Line_1"] = f"SET {actuator_name} = {value}"

        self.program_name_list.append(program_name)

    def make_actuators(self, plant: Plant, rooms: Dict[str, Room]):
        """
        Make actuators for plant components
        """
        self._make_actuators(plant=plant, rooms=rooms)
