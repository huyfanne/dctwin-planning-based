"""
Inputs values for the CFD model
"""

from typing import OrderedDict, Optional
from pydantic import BaseModel


class ACUInputs(BaseModel):
    cooling_type: Optional[str] = "DX"
    cooling_capacity: Optional[float]
    supply_air_temperature: Optional[float] # unit(C)
    supply_air_volume_flow_rate: Optional[float] # unit(m3/s)
    fan_power: Optional[float]


class ServerInputs(BaseModel):
    fan_type: Optional[str]
    volume_flow_rate: Optional[float] # unit(m3/s)
    volume_flow_rate_ratio: Optional[float] # unit(m3/s/W)
    rated_power: Optional[float] # unit(W)
    input_power: Optional[float] # unit(W)


class Inputs(BaseModel):
    acus: Optional[OrderedDict[str, ACUInputs]]
    servers: Optional[OrderedDict[str, ServerInputs]]