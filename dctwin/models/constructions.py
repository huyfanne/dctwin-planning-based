import json
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field, validator

from dctwin.models.basics import ACUConfig, RoomConfig, ServerConfig, Size, Vertex, Face
from dctwin.models.objects import Objects


class VentOpening(BaseModel):
    width: Decimal
    length: Decimal
    offset_h: Decimal
    offset_v: Decimal


class PartitionWall(BaseModel):
    size: Size
    placement: Vertex
    vent_opening_list: List[VentOpening] = Field(default_factory=list)


class Duct(BaseModel):
    placement: Vertex
    size: Size
    extend_to_floor: Optional[List[Face]]


class Ceiling(BaseModel):
    height: Decimal
    duct_in_list: List[Duct]
    duct_out_list: List[Duct]


class RaisedFloor(BaseModel):
    placement: Vertex


class Constructions(BaseModel):
    partition_wall_list: List[PartitionWall] = Field(default_factory=list)
    raised_floor: Optional[RaisedFloor]
    ceiling: Optional[Ceiling]


class Room(BaseModel):
    name: str
    height: Decimal
    plane_outline: List[Vertex]

    constructions: Constructions
    objects: Objects

    # Probe locations
    probes: List[Vertex] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: float}

    @validator('objects')
    def validate_objects(cls, v):
        for server in v.servers.values():
            rack = v.racks[server.rack_id]
            server.orientation = rack.orientation
            server.width = v.rack_models[rack.model].size.dx
        return v

    def extract_config(self) -> RoomConfig:
        return RoomConfig(
            acu_configs={
                acu.id: ACUConfig(
                    supply_temperature=acu.supply_temperature,
                    flow_rate=acu.flow_rate,
                )
                for acu in self.objects.acus.values()
            },
            server_configs={
                server.id: ServerConfig(
                    heat_load=server.heat_load, flow_rate=server.flow_rate
                )
                for server in self.objects.servers.values()
            },
        )

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, 'w') as f:
            yaml.safe_dump(json.loads(self.json()), f)

    @classmethod
    def load(cls, file_path: 'str') -> 'Room':
        with open(file_path) as f:
            return cls(**yaml.safe_load(f))

    def dump_config(self, file_path: Union[str, Path]) -> None:
        with open(file_path, 'w') as f:
            yaml.safe_dump(json.loads(self.extract_config().json()), f)

    def load_config(self, file_path: Union[str, Path]) -> None:
        with open(file_path) as f:
            config = RoomConfig(**yaml.safe_load(f))
        self.apply_config(config)

    def apply_config(self, config: RoomConfig) -> None:
        """Update acu and server by config object"""
        for acu_id, acu_config in config.acu_configs.items():
            acu = self.objects.acus.get(acu_id)
            acu.fan_speed_ratio = acu_config.fan_speed_ratio
            acu.supply_temperature = acu_config.supply_temperature
            acu.config_flow_rate = acu_config.flow_rate
        for server_id, server_config in config.server_configs.items():
            server = self.objects.servers.get(server_id)
            server.config_heat_load = server_config.heat_load
            server.config_flow_rate = server_config.flow_rate
        self.probes = config.probes
