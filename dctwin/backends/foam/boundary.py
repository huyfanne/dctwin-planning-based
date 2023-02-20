import abc

from dctwin.models.room import Room
from dctwin.models.room import ACU, Server


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

    @property
    @abc.abstractmethod
    def T(self):
        pass

    @property
    @abc.abstractmethod
    def U(self):
        pass


class RoomBoundary(Boundary):
    def __init__(self, room: Room) -> None:
        self.room = room

    def generate_boundary(self, type_define):
        ceiling = f"ceiling_1 {type_define}"
        if self.room.constructions.false_ceiling is None:
            ceiling = ""

        floor = f"floor_1 {type_define}"
        if self.room.constructions.raised_floor is None:
            floor = ""

        boxes_types_index = {}
        boxes_name_list = []
        for box in self.room.constructions.boxes.values():
            if (box.geometry.model not in boxes_types_index):
                boxes_types_index[box.geometry.model] = 1
            else:
                boxes_types_index[box.geometry.model] += 1
            boxes_name_list.append(f"box_{box.geometry.model}_{boxes_types_index[box.geometry.model]}")
        boxes_boundary = "\n".join(
            [
                f"{box_name} {type_define}"
                for box_name in boxes_name_list
            ]
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
            [
                f"rack_panel_{key} {type_define}"
                for key in rack_with_panel
            ]
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
    def T(self):
        return self.generate_boundary(self.zero_gradient)

    @property
    def U(self):
        return self.generate_boundary(self.no_slip)


class ACUBoundary(Boundary):
    def __init__(self, id: str, acu: ACU) -> None:
        self.id = id
        self.object = acu
        self.supply_kelvin = round(acu.geometry.min_temperature + 273.15, 2)
        self.flow_rate = round(acu.geometry.flow_rate, 6)
        self.cooling_capacity = round(acu.geometry.cooling_capacity, 6)

    @property
    def p_rgh(self):
        return f"""
        acu_return_{self.id}
        {{
            type        fixedValue;
            value 		$internalField;
        }}
        """

    @property
    def T(self):
        t_sink = f"tSink_{self.id}"
        return f"""
        acu_supply_{self.id}
        {{
            type            exprFixedValue;
            value           $internalField;
            valueExpr      "max(t1,t2)";
            variables
            (
                "{t_sink}{{acu_return_{self.id}}} = weightAverage(T)"
                "coolingCapacity = {self.cooling_capacity}"
                "rho = 1.2"
                "flowrate = {self.flow_rate}"
                "mfr = flowrate*rho"		
                "Cp = 1006"
                "t1={t_sink}-(coolingCapacity*1000/(mfr*Cp))"
                "del_t=0.5"
                "min_temperature = {self.supply_kelvin}"
                "t2= min_temperature + del_t"
            );
        }}
        acu_return_{self.id} {self.zero_gradient}
        acu_wall_{self.id} {self.zero_gradient}
        """


    @property
    def U(self):
        supply = f"""
        {{
            type                flowRateInletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        }}
        """
        _return = f"""
        {{
            type                flowRateOutletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        }}
        """
        if self.flow_rate == 0:
            supply = self.no_slip
            _return = self.no_slip
        return f"""
        acu_supply_{self.id} {supply}
        acu_return_{self.id} {_return}
        acu_wall_{self.id} {self.no_slip}
        """


class ServerBoundary(Boundary):
    specificheat = 1006
    density = 1.19

    def __init__(self, id: str, server: Server) -> None:
        self.id = id
        self.object: Server = server
        self.heat_load = server.geometry.heat_load
        self.flow_rate = round(server.geometry.flow_rate, 6)
        self.mass_flow_rate = self.density * self.flow_rate
        self.flow_value = self.mass_flow_rate * self.specificheat
        self.area = server.geometry.inlet_area


    @property
    def T(self):
        t_sink = f"tSink_{self.id}"
        value = f"({t_sink}+({self.heat_load}/{self.flow_value}))"
        if self.flow_rate == 0:
            outlet = self.zero_gradient
        else:
            outlet = f"""
            {{
                type            exprFixedValue;
                value           $internalField;
                valueExpr       "{value}";
                variables
                (
                    "{t_sink}{{server_inlet_{self.id}}} = weightAverage(T)"
                );
            }}"""
        return f"""
        server_outlet_{self.id} {outlet}
        server_wall_{self.id} {self.zero_gradient}
        server_inlet_{self.id} {self.zero_gradient}
        """


    @property
    def U(self):
        inlet = f"""
        {{
            type                flowRateOutletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        }}
        """
        outlet = f"""
        {{
            type                flowRateInletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        }}
        """
        if self.flow_rate == 0:
            inlet = self.no_slip
            outlet = self.no_slip
        return f"""
        server_inlet_{self.id} {inlet}
        server_outlet_{self.id} {outlet}
        server_wall_{self.id} {self.no_slip}
        """