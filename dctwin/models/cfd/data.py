"""
Inputs values for the CFD model
"""

from typing import OrderedDict, Optional, Dict

from .utils import BaseModel


class ACUInputs(BaseModel):
    supply_air_temperature: Optional[float]  # unit(C)
    supply_air_volume_flow_rate: Optional[float]  # unit(m3/s)


class ServerInputs(BaseModel):
    input_power: Optional[float]  # unit(W)


class SensorMeasurements(BaseModel):
    temperature: Optional[float]  # unit(C)


class Inputs(BaseModel):
    acus: Optional[OrderedDict[str, ACUInputs]]
    servers: Optional[OrderedDict[str, ServerInputs]]

    @property
    def format(self) -> Dict:
        data = {
            "supply_air_temperatures": {},
            "supply_air_volume_flow_rates": {},
            "server_powers": {},
        }
        for acu, val in self.acus.items():
            data["supply_air_temperatures"].update({acu: val.supply_air_temperature})
            data["supply_air_volume_flow_rates"].update(
                {acu: val.supply_air_volume_flow_rate}
            )
        for server, val in self.servers.items():
            data["server_powers"].update({server: val.input_power})

        return data


class Labels(BaseModel):

    sensor_measurements: OrderedDict[str, SensorMeasurements]

    @property
    def format(self) -> Dict:
        data = {"temperatures": {}}
        for sensor, val in self.sensor_measurements.items():
            data["temperatures"].update({sensor: val.temperature})
        return data


class CFDData(BaseModel):
    inputs: Inputs
    labels: Labels

    @property
    def format(self) -> Dict:
        data = {"inputs": self.inputs.format, "labels": self.labels.format}
        return data
