import abc
from dctwin.models.constructions import Room
from dctwin.models.objects import ACU, Server


class Boundary(abc.ABC):

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
        if self.room.constructions.ceiling is None:
            ceiling = ""
        else:
            ceiling = ceiling + "\n".join(
                [
                    f"ceiling_duct_{index} {type_define}"
                    for index, _ in enumerate(self.room.constructions.ceiling.duct_list)
                ]
            )

        floor = f"floor_1 {type_define}"
        if self.room.constructions.raised_floor is None:
            floor = ""

        containments_boundary = "\n".join(
            [
                f"containment_{index} {type_define}"
                for index, _ in enumerate(list(self.room.constructions.containments))
            ]
        )
        partition_wall_boundary = "\n".join(
            [
                f"partition_wall_{index} {type_define}"
                for index, _ in enumerate(list(self.room.constructions.partition_walls))
            ]
        )

        rack_boundary = "\n".join(
            [
                f"rack_wall_{rack.id} {type_define}"
                for rack in self.room.objects.racks.values()
            ]
        )
        return f"""
        room_wall_1 {type_define}
        {ceiling}
        {floor}
        {containments_boundary}
        {partition_wall_boundary}
        {rack_boundary}
        """

    @property
    def T(self):
        return self.generate_boundary(self.zero_gradient)

    @property
    def U(self):
        return self.generate_boundary(self.no_slip)


class ACUBoundary(Boundary):
    def __init__(self, acu: ACU) -> None:
        self.object = acu
        self.supply_kelvin = round(acu.supply_temperature + 273.15, 2)
        self.flow_rate = round(acu.flow_rate, 6)

    @property
    def p_rgh(self):
        return f"""
        acu_return_{self.object.id}
        {{
            type        fixedValue;
            value 		$internalField;
        }}
        """

    @property
    def T(self):
        return f"""
        acu_supply_{self.object.id}
        {{
            type    fixedValue;
            value   uniform {self.supply_kelvin};
        }}
        acu_return_{self.object.id} {self.zero_gradient}
        acu_wall_{self.object.id} {self.zero_gradient}
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
        acu_supply_{self.object.id} {supply}
        acu_return_{self.object.id} {_return}
        acu_wall_{self.object.id} {self.no_slip}
        """


class ServerBoundary(Boundary):
    specificheat = 1006
    density = 1.19

    def __init__(self, server: Server) -> None:
        self.object = server
        self.heat_load = server.heat_load
        self.flow_rate = round(server.flow_rate, 6)
        self.mass_flow_rate = self.density * self.flow_rate
        self.flow_value = self.mass_flow_rate * self.specificheat

        self.area = server.inlet_area
        if server.dynamic_temperature_low:
            self.t_low = server.dynamic_temperature_low + 273.15
            self.t_high = server.dynamic_temperature_high + 273.15
            self.flow_rate_high = server.dynamic_flow_rate_high
            self.slope = (self.flow_rate_high - server.flow_rate) / (
                self.t_high - self.t_low
            )

    @property
    def T(self):
        t_sink = f"tSink_{self.object.id}"
        value = f"({t_sink}+({self.heat_load}/{self.flow_value}))"
        if self.flow_rate == 0:
            outlet = self.zero_gradient
        else:
            outlet = f"""
            {{
                type            exprFixedValue;
                // value           $internalField;
                valueExpr       "{value}";
                variables
                (
                    "{t_sink}{{server_inlet_{self.object.id}}} = weightAverage(T)"
                );
            }}"""
        return f"""
        server_outlet_{self.object.id} {outlet}
        server_wall_{self.object.id} {self.zero_gradient}
        server_inlet_{self.object.id} {self.zero_gradient}
        """

    @property
    def dynamic_t(self):
        t_sink = f"tSink_{self.object.id}"
        value = f"({t_sink}+({self.heat_load}/{self.flow_value}))"
        u_sink = f"uSink_{self.object.id}"
        changing_value = f"{self.heat_load}/({u_sink}*{self.object.outlet_area}*{self.density}*{self.specificheat})"
        weight_u = "weightAverage(U.y())"
        if self.object.orientation == 90:
            weight_u = "-weightAverage(U.x())"
        if self.object.orientation == 180:
            weight_u = "-weightAverage(U.y())"
        if self.object.orientation == 270:
            weight_u = "weightAverage(U.x())"
        f"""
        {{
            type            exprFixedValue;
            value           $internalField;
            valueExpr       "{t_sink} <= {self.t_low}? {value}:({changing_value})";
            variables
            (
                "{t_sink}{{server_inlet_{self.object.id}}} = weightAverage(T)"
                "{u_sink}{{server_inlet_{self.object.id}}} = {weight_u}"
            );
        }}
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
        server_inlet_{self.object.id} {inlet}
        server_outlet_{self.object.id} {outlet}
        server_wall_{self.object.id} {self.no_slip}
        """

    @property
    def dynamic_inlet(self):
        t_sink = f"t_Sink_{self.object.id}"
        value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(0,(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0):vector(0,{self.flow_rate_high}/{self.area},0):vector(0,{self.flow_rate}/{self.area},0)"
        if self.object.orientation == 90:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(-(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0,0):vector(-{self.flow_rate_high}/{self.area},0,0):vector(-{self.flow_rate}/{self.area},0,0)"
        elif self.object.orientation == 180:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(0,-(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0):vector(0,-{self.flow_rate_high}/{self.area},0):vector(0,-{self.flow_rate}/{self.area},0)"
        elif self.object.orientation == 270:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector((({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0,0):vector({self.flow_rate_high}/{self.area},0,0):vector({self.flow_rate}/{self.area},0,0)"
        return f"""
        {{
            type            exprFixedValue;
            value           $internalField;
            valueExpr       "{value_expr}";
            variables
            (
                "{t_sink}{{server_inlet_{self.object.id}}} = weightAverage(T)"
            );
        }}
        """

    @property
    def dynamic_outlet(self):
        t_sink = f"t_Sink_{self.object.id}"
        value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(0,(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0):vector(0,{self.flow_rate_high}/{self.area},0):vector(0,{self.flow_rate}/{self.area},0)"
        if self.object.orientation == 90:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(-(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0,0):vector(-{self.flow_rate_high}/{self.area},0,0):vector(-{self.flow_rate}/{self.area},0,0)"
        elif self.object.orientation == 180:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector(0,-(({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0):vector(0,-{self.flow_rate_high}/{self.area},0):vector(0,-{self.flow_rate}/{self.area},0)"
        elif self.object.orientation == 270:
            value_expr = f"({t_sink}>={self.t_low})?({t_sink}<={self.t_high})?vector((({self.slope}*({t_sink}-{self.t_low})) + {self.flow_rate})/{self.area},0,0):vector({self.flow_rate_high}/{self.area},0,0):vector({self.flow_rate}/{self.area},0,0)"
        return f"""
        {{
            type            exprFixedValue;
            value           $internalField;
            valueExpr       "{value_expr}";
            variables
            (
                "{t_sink}{{server_inlet_{self.object.id}}} = weightAverage(T)"
            );
        }}
        """
