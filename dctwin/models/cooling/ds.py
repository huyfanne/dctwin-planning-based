from torch import Tensor
from typing import Union


class NodeData:
    """
    Data structure to store the fluid properties of a node in a plant loop
    """
    def __init__(self, T: Union[float, Tensor], M: Union[float, Tensor]):
        self.T = T
        self.M = M

    @property
    def temperature(self):
        return self.T

    @property
    def mass_flow_rate(self):
        return self.M


class BranchData:
    """
    Data structure to store the fluid properties of a branch in a plant loop
    """
    def __init__(
        self,
        inlet_temperature: float | Tensor,
        inlet_mass_flow_rate: float | Tensor,
        outlet_temperature: float | Tensor,
        outlet_mass_flow_rate: float | Tensor
    ):
        self.inlet = NodeData(inlet_temperature, inlet_mass_flow_rate)
        self.outlet = NodeData(outlet_temperature, outlet_mass_flow_rate)

    @property
    def inlet_T(self):
        return self.inlet.T

    @property
    def inlet_M(self):
        return self.inlet.M

    @property
    def outlet_T(self):
        return self.outlet.T

    @property
    def outlet_M(self):
        return self.outlet.M

    def set_inlet(self, temperature: Union[float, Tensor], mass_flow_rate: Union[float, Tensor]):
        self.inlet.T = temperature
        self.inlet.M = mass_flow_rate

    def set_outlet(self, temperature: Union[float, Tensor], mass_flow_rate: Union[float, Tensor]):
        self.outlet.T = temperature
        self.outlet.M = mass_flow_rate
