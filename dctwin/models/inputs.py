from typing import OrderedDict
from pydantic import BaseModel


class ACUInputs(BaseModel):
    flow_rate: float
    min_temperature: float


class ServerInputs(BaseModel):
    flow_rate: float
    heat_load: float


class Inputs(BaseModel):
    acus: OrderedDict[str, ACUInputs]
    servers: OrderedDict[str, ServerInputs]
