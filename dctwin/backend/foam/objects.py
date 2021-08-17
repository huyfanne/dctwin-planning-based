import abc
from dctwin.models.constructions import Room
from dctwin.models.objects import ACU


class Boundary(abc.ABC):
    @property
    @abc.abstractmethod
    def T(self):
        pass

    @property
    @abc.abstractmethod
    def U(self):
        pass


class RoomBoundary:
    def __init__(self, room: Room) -> None:
        self.room = room

    @property
    def T(self):
        ceiling = f"""       
        "ceiling_1"
        {{
            type            zeroGradient;
        }}
        """
        floor = f"""
        "floor_1"
        {{
            type            zeroGradient;
        }}"""
        if self.room.constructions.ceiling is None:
            ceiling = ""
        if self.room.constructions.raised_floor is None:
            floor = ""
        return f"""
        "room_wall_1"
        {{
            type            zeroGradient;
        }}
        {ceiling}
        {floor}
        """

    @property
    def U(self):
        ceiling = f"""       
        "ceiling_1"
        {{
            type            noSlip;
        }}
        """
        floor = f"""
        "floor_1"
        {{
            type            noSlip;
        }}"""
        if self.room.constructions.ceiling is None:
            ceiling = ""
        if self.room.constructions.raised_floor is None:
            floor = ""
        return f"""
        "room_wall_1"
        {{
            type            noSlip;
        }}
        {ceiling}
        {floor}
        """


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
