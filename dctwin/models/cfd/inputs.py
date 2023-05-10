"""
Inputs values for the CFD model
"""

from typing import OrderedDict, Optional

from .utils import BaseModel


class ACUInputs(BaseModel):
    cooling_capacity: Optional[float] # unit(kW)
    supply_air_temperature: Optional[float] # unit(C)
    supply_air_volume_flow_rate: Optional[float] # unit(m3/s)


class ServerInputs(BaseModel):
    input_power: Optional[float] # unit(W)


class Inputs(BaseModel):
    acus: Optional[OrderedDict[str, ACUInputs]]
    servers: Optional[OrderedDict[str, ServerInputs]]
