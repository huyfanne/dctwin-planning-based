"""
Building is the highest level object in a data center.
It contains all the data halls (rooms) and the built-in facilities.
"""
import json

from pathlib import Path
from typing import Union, Optional, Dict, OrderedDict, List
from pydantic import BaseModel, validator, Field

from .room import Room, RoomConstruction
from .acu import ACU
from .box import Box
from .server import Server
from .rack import RackConstruction, Rack
from .utils import convert_json_file
from .models import Model
from .inputs import Inputs, ServerInputs, ACUInputs


class BuildingConstruction(BaseModel):
    """ Building construction is used to define the data halls in a building """
    rooms: OrderedDict[str, Room]


class Building(BaseModel):
    """ Building object: the highest level object in a data center
    """
    models: Optional[Model]
    inputs: Optional[Inputs] = Field(default_factory=Inputs)
    constructions: BuildingConstruction
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    @validator("constructions")
    def _validate_building_constructions(
        cls,
        building_constructions: BuildingConstruction,
        values: Dict
    ) -> BuildingConstruction:
        cls._validate_rooms(building_constructions.rooms, values["models"], values["inputs"])
        return building_constructions

    @classmethod
    def _validate_rooms(cls, rooms: Dict, models: Model, inputs: Inputs) -> None:
        for room_id, room in rooms.items():
            cls._validate_id(room_id)
            cls._validate_room_constructions(room.constructions, models, inputs)

    @classmethod
    def _validate_room_constructions(
        cls,
        room_construction: RoomConstruction,
        models: Model,
        inputs: Inputs,
    ) -> None:
        cls._validate_acus(room_construction.acus, models, inputs.acus)
        cls._validate_boxes(room_construction.boxes, models)
        cls._validate_racks(room_construction.racks, models, inputs)
        cls._validate_sensors(room_construction.sensors)

    @classmethod
    def _validate_acus(cls, acus: Dict, models: Model, inputs: Dict) -> None:
        for acu_id, acu in acus.items():
            cls._validate_id(acu_id)
            cls._validate_geometry_models(acu, models.geometry_models.acus) if models.geometry_models else None
            cls._validate_cooling_models(acu, models.cooling_models.acus) if models.cooling_models  else None
            cls._validate_power_models(acu, models.power_models.acus) if models.power_models else None
            cls._validate_inputs(acu, inputs.get(acu_id)) if inputs else None

    @classmethod
    def _validate_boxes(cls, boxes: Dict, models: Model) -> None:
        for box_id, box in boxes.items():
            cls._validate_id(box_id)
            cls._validate_geometry_models(box, models.geometry_models.boxes) if models.geometry_models else None

    @classmethod
    def _validate_racks(cls, racks: Dict, models: Model, inputs: Inputs) -> None:
        for rack_id, rack in racks.items():
            cls._validate_id(rack_id)
            cls._validate_geometry_models(rack, models.geometry_models.racks) if models.geometry_models else None
            cls._validate_rack_constructions(rack, rack.constructions, models, inputs)

    @classmethod
    def _validate_rack_constructions(
        cls,
        rack: Rack,
        rack_constructions: RackConstruction,
        models: Model,
        inputs: Inputs,
    ) -> None:
        cls._validate_servers(rack, rack_constructions.servers, models, inputs.servers)

    @classmethod
    def _validate_servers(cls, rack: Rack, servers: Dict, models: Model, inputs: Dict) -> None:
        occupied_rack_slot = {}
        for server_id, server in servers.items():
            cls._validate_id(server_id)
            cls._validate_geometry_models(server, models.geometry_models.servers) if models.geometry_models else None
            cls._validate_cooling_models(server, models.cooling_models.acus) if models.cooling_models else None
            cls._validate_power_models(server, models.power_models.acus) if models.power_models else None
            cls._validate_inputs(server, inputs.get(server_id)) if inputs else None
            cls._validate_server_occupation(rack, server, server_id, occupied_rack_slot)

    @classmethod
    def _validate_server_occupation(cls, rack: Rack, server: Server, server_id: str, occupied_rack_slot: Dict) -> None:
        server.geometry.orientation = rack.geometry.orientation
        slot_position = int(server.geometry.slot_position)
        slot_occupation = int(server.geometry.slot_occupation)
        num_slots = int(rack.geometry.slot)
        if slot_position < 1 or slot_occupation + slot_position > num_slots + 1:
            raise ValueError(
                f"invalid server slot/occupation:"
                f"Server({server_id}, slot={slot_position},"
                f"occupation={slot_occupation})"
            )
        for i in range(slot_position, slot_position + slot_occupation):
            if i not in occupied_rack_slot:
                occupied_rack_slot[i] = server_id
            else:
                raise ValueError(
                    f"invalid server slot/occupation: "
                    f"Server({server_id}) has collision with "
                    f"Server({occupied_rack_slot[i]})"
                )

    @classmethod
    def _validate_sensors(cls, sensors: Dict) -> None:
        for sensor_id, sensor in sensors.items():
            cls._validate_id(sensor_id)

    @classmethod
    def _validate_id(cls, _id: str) -> None:
        if not _id.isidentifier():
            raise ValueError(f"must be valid identifier: {_id}")

    @classmethod
    def _validate_geometry_models(
        cls,
        obj: Union[ACU, Server, Rack, Box],
        models: Dict
    ) -> None:
        model_name = obj.geometry.model
        if isinstance(obj, ACU) and models is not None:
            obj.geometry.size = models.get(model_name).size
            obj.geometry.supply_face = models.get(model_name).supply_face
            obj.geometry.return_face = models.get(model_name).return_face
        elif isinstance(obj, Rack) and models is not None:
            obj.geometry.size = models.get(model_name).size
            obj.geometry.slot = models.get(model_name).slot
            obj.geometry.first_slot_offset = models.get(model_name).first_slot_offset
        elif isinstance(obj, Server) and models is not None:
            obj.geometry.slot_occupation = models.get(model_name).slot_occupation
            obj.geometry.width = models.get(model_name).width
            obj.geometry.depth = models.get(model_name).depth
        elif isinstance(obj, Box) and models is not None:
            obj.geometry.faces = models.get(model_name).faces
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object geometry model is not defined."
            )

    @classmethod
    def _validate_power_models(
        cls,
        obj: Union[ACU, Server],
        models: Dict
    ) -> None:
        model_name = obj.power.model
        if isinstance(obj, ACU) and models is not None:
            obj.rated_fan_power = models.get(model_name).rated_fan_power
        elif isinstance(obj, Server) and models is not None:
            obj.rated_power = models.get(model_name).rated_power
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object power model is not defined."
            )

    @classmethod
    def _validate_cooling_models(
        cls,
        obj: Union[ACU, Server],
        models: Dict
    ) -> None:
        model_name = obj.cooling.model
        if isinstance(obj, ACU) and models is not None:
            obj.cooling.cooling_type = models.get(model_name).cooling_type
            obj.cooling.cooling_capacity = models.get(model_name).cooling_capacity
        elif isinstance(obj, Server) and models is not None:
            obj.cooling.fan_type = models.get(model_name).fan_type
            obj.cooling.volume_flow_rate_ratio = models.get(model_name).volume_flow_rate_ratio
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object cooling model is not defined."
            )

    @classmethod
    def _validate_inputs(
        cls,
        obj: Union[ACU, Server],
        inputs: Union[ACUInputs, ServerInputs],
    ) -> None:
        if isinstance(obj, ACU) and isinstance(inputs, ACUInputs):
            obj.cooling.supply_air_temperature = inputs.supply_air_temperature
            obj.cooling.supply_air_volume_flow_rate = inputs.supply_air_volume_flow_rate
            obj.cooling.cooling_capacity = inputs.cooling_capacity
        elif isinstance(obj, Server) and isinstance(inputs, ServerInputs):
            obj.power.input_power = inputs.input_power
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object inputs is not defined."
            )

    @property
    def rooms(self) -> List[Room]:
        return list(self.constructions.rooms.values())

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2))

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "Building":
        with open(file_path) as f:
            return cls(**convert_json_file(json.load(f)))
