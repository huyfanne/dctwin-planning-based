from dctwin.models.objects import ACU


class Boundary:
    def __init__(self) -> None:
        pass


class ACUBoundary:
    def __init__(self, acu: ACU) -> None:
        self.object = acu
        self.supply_kelvin = round(acu.supply_temperature + 273.15, 2)

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
