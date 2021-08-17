import abc
from dctwin.models.constructions import Room
from dctwin.models.objects import ACU


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
        ceiling = f""""ceiling_1" {type_define}"""
        if self.room.constructions.ceiling is None:
            ceiling = ""
        else:
            for index in enumerate(self.room.constructions.ceiling.duct_list):
                "".join(ceiling, f"ceiling_duct_{index} {type_define}\n")

        floor = f""""floor_1" {type_define}"""
        if self.room.constructions.raised_floor is None:
            floor = ""

        containments_boundary = ""
        for index, _ in enumerate(list(self.room.constructions.containments)):
            "".join(
                containments_boundary,
                f"containment_{index} {type_define}\n",
            )
        partition_wall_boundary = ""
        for index, _ in enumerate(list(self.room.constructions.partition_walls)):
            "".join(
                partition_wall_boundary,
                f"partition_wall_{index} {type_define}\n",
            )

        rack_boundary = "\n".join(
            [
                f"rack_wall_{rack.id} {type_define}"
                for rack in self.room.objects.racks.values()
            ]
        )
        return f"""
        "room_wall_1" {type_define}
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


class ACUBoundary:
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
        "acu_return_{self.object.id}"
        {{
            type    zeroGradient;
        }}
        "acu_wall_{self.object.id}"
        {{
            type    zeroGradient;
        }}
        """

    @property
    def U(self):
        supply = f"""
            type                flowRateInletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        """
        _return = f"""
            type                flowRateOutletVelocity;
            volumetricFlowRate  {self.flow_rate};
            value               uniform (0 0 0);
        """
        if self.flow_rate != 0:
            supply = "type    noSlip;"
            _return = "type    noSlip;"
        return f"""
        "acu_supply_{self.object.id}"
        {{
            {supply}
        }}
        "acu_return_{self.object.id}"
        {{
            {_return}
        }}
        "acu_wall_{self.object.id}"
        {{
            type    noSlip;
        }}
        """
