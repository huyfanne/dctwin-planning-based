import abc
import numpy as np
from dctwin.models import Room, ACU, Server


class Boundary(abc.ABC):
    """A class to generate the boundary condition of the foam simulation"""

    zero_gradient = """
    {
        type            zeroGradient;
    }
    """
    no_slip = """
    {
        type            noSlip;
    }
    """

    air_specific_heat = 1006
    rho_air = 1.19

    @property
    @abc.abstractmethod
    def T(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def U(self) -> str:
        pass


class RoomBoundary(Boundary):
    def __init__(self, room: Room) -> None:
        self.room = room

    def generate_boundary(self, type_define) -> str:
        ceiling = f"ceiling_1 {type_define}"
        if self.room.constructions.false_ceiling is None:
            ceiling = ""

        floor = f"floor_1 {type_define}"
        if self.room.constructions.raised_floor is None:
            floor = ""

        boxes_types_index = {}
        boxes_name_list = []
        for box in self.room.constructions.boxes.values():
            if box.geometry.model not in boxes_types_index:
                boxes_types_index[box.geometry.model] = 1
            else:
                boxes_types_index[box.geometry.model] += 1
            boxes_name_list.append(
                f"box_{box.geometry.model}_{boxes_types_index[box.geometry.model]}"
            )
        boxes_boundary = "\n".join(
            [f"{box_name} {type_define}" for box_name in boxes_name_list]
        )

        rack_boundary = "\n".join(
            [
                f"rack_wall_{key} {type_define}"
                for key, rack in self.room.constructions.racks.items()
            ]
        )
        rack_with_panel = []
        for key, rack in self.room.constructions.racks.items():
            if rack.geometry.has_blanking_panel:
                rack_with_panel.append(key)

        rack_panel_boundary = "\n".join(
            [f"rack_panel_{key} {type_define}" for key in rack_with_panel]
        )
        return f"""
        room_wall_1 {type_define}
        {ceiling}
        {floor}
        {boxes_boundary}
        {rack_boundary}
        {rack_panel_boundary}
        """

    @property
    def T(self) -> str:
        return self.generate_boundary(self.zero_gradient)

    @property
    def U(self) -> str:
        return self.generate_boundary(self.no_slip)


class ACUBoundary(Boundary):
    def __init__(self, acu_id: str, acu: ACU) -> None:
        self.acu_id = acu_id
        self.object = acu
        self.supply_kelvin = round(acu.cooling.supply_air_temperature + 273.15, 2)
        self.supply_air_volume_flow_rate = round(
            acu.cooling.supply_air_volume_flow_rate, 6
        )
        self.supply_air_mass_flow_rate = self.rho_air * self.supply_air_volume_flow_rate
        self.cooling_capacity = round(acu.cooling.cooling_capacity, 6)  # unit: kW

    @property
    def p_rgh(self) -> str:
        return f"""
        acu_return_{self.acu_id}
        {{
            type        fixedValue;
            value 		$internalField;
        }}
        """

    @property
    def T(self) -> str:
        t_sink = f"tSink_{self.acu_id}"
        if np.isclose(self.supply_air_volume_flow_rate, 0):
            outlet = self.zero_gradient
        else:
            outlet = f"""
            {{
                type            exprFixedValue;
                value           $internalField;
                valueExpr       "max(t1,t2)";
                variables
                (
                    "{t_sink}{{acu_return_{self.acu_id}}} = weightAverage(T)"
                    "coolingCapacity = {self.cooling_capacity}"		
                    "supplyAirMassFlowRate = {self.supply_air_mass_flow_rate}"
                    "t1 = {t_sink} - (coolingCapacity * 1000 / (supplyAirMassFlowRate * {self.air_specific_heat}))"
                    "t2 = {self.supply_kelvin}"
                );
            }}
            """
        return f"""
        acu_supply_{self.acu_id} {outlet}
        acu_return_{self.acu_id} {self.zero_gradient}
        acu_wall_{self.acu_id} {self.zero_gradient}
        """

    @property
    def U(self) -> str:
        if np.isclose(self.supply_air_volume_flow_rate, 0):
            supply = self.no_slip
            _return = self.no_slip
        else:
            supply = f"""
            {{
                type                flowRateInletVelocity;
                volumetricFlowRate  {self.supply_air_volume_flow_rate};
                value               uniform (0 0 0);
            }}
            """
            _return = f"""
            {{
                type                flowRateOutletVelocity;
                volumetricFlowRate  {self.supply_air_volume_flow_rate};
                value               uniform (0 0 0);
            }}
            """
        return f"""
        acu_supply_{self.acu_id} {supply}
        acu_return_{self.acu_id} {_return}
        acu_wall_{self.acu_id} {self.no_slip}
        """


class ServerBoundary(Boundary):
    def __init__(self, server_id: str, server: Server) -> None:
        self.server_id = server_id
        self.object: Server = server
        self.input_power = server.power.input_power
        self.server_volume_flow_rate = round(server.volume_flow_rate, 6)
        self.server_mass_flow_rate = self.rho_air * self.server_volume_flow_rate

    @property
    def T(self) -> str:
        t_sink = f"tSink_{self.server_id}"
        if np.isclose(self.server_mass_flow_rate, 0):
            outlet = self.zero_gradient
        else:
            value = f"{t_sink}+{self.input_power / (self.server_mass_flow_rate * self.air_specific_heat)}"
            outlet = f"""
            {{
                type            exprFixedValue;
                value           $internalField;
                valueExpr       "{value}";
                variables
                (
                    "{t_sink}{{server_inlet_{self.server_id}}} = weightAverage(T)"
                );
            }}"""
        return f"""
        server_outlet_{self.server_id} {outlet}
        server_wall_{self.server_id} {self.zero_gradient}
        server_inlet_{self.server_id} {self.zero_gradient}
        """

    @property
    def U(self) -> str:
        if np.isclose(self.server_mass_flow_rate, 0):
            inlet = self.no_slip
            outlet = self.no_slip
        else:
            inlet = f"""
            {{
                type                flowRateOutletVelocity;
                volumetricFlowRate  {self.server_volume_flow_rate};
                value               uniform (0 0 0);
            }}
            """
            outlet = f"""
            {{
                type                flowRateInletVelocity;
                volumetricFlowRate  {self.server_volume_flow_rate};
                value               uniform (0 0 0);
            }}
            """
        return f"""
        server_inlet_{self.server_id} {inlet}
        server_outlet_{self.server_id} {outlet}
        server_wall_{self.server_id} {self.no_slip}
        """
