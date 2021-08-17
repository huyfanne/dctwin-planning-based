from dctwin.models.objects import ACU


class Boundary:
    def __init__(self) -> None:
        pass


class ACUBoundary:
    def __init__(self, acu: ACU) -> None:
        self.object = acu
        self.supply_kelvin = round(acu.supply_temperature + 273.15, 2)
        self.flow_rate = round(acu.flow_rate, 6)

    @property
    def T(self):
        return f"""
        acu_supply_{self.object.id}
        {{
            type    fixedValue;
            value   uniform {self.supply_kelvin}
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
        flow_boundary = (
            f"""
        "acu_supply_{self.object.id}"
        {{
            type    noSlip;
        }}
        "acu_return_{self.object.id}"
        {{
            type    noSlip;
        }}
        """
            if self.flow_rate == 0
            else f"""
        acu_supply_{self.object.id}
        {{
            type                flowRateInletVelocity;
            volumetricFlowRate  {{ acu.flow_rate if acu.flow_rate != 0 else 1e-10 }};
            value               uniform (0 0 0);
        }}
        "acu_return_{self.object.id}"
        {{
            type                flowRateOutletVelocity;
            volumetricFlowRate  {{ acu.flow_rate if acu.flow_rate != 0 else 1e-10 }};
            value               uniform (0 0 0);
        }}
        """
        )
        return f"""
        {flow_boundary}
        "acu_wall_{self.object.id}"
        {{
            type    noSlip;
        }}
        """
