""" Room object
"""
import json
import numpy as np
from typing import Optional, OrderedDict, List, Tuple, Dict, Union

from pydantic import Field, validator
from pathlib import Path

from .basics import Vertex, Face
from .panel import Panel
from .box import Box
from .rack import Rack, RackConstruction
from .sensor import Sensor
from .acu import ACU, ACUFace
from .server import Server
from .models import Model
from .data import Inputs, ServerInputs, ACUInputs
from .utils import rotate, euclidean_distance, BaseModel


class RoomGeometry(BaseModel):
    height: float
    plane: List[Vertex]


class RoomConstruction(BaseModel):
    """ RoomConstruction is used to build the objects in a room
    """
    raised_floor: Optional[Panel]
    false_ceiling: Optional[Panel]
    boxes: Optional[OrderedDict[str, Box]]
    acus: OrderedDict[str, ACU]
    racks: OrderedDict[str, Rack]
    sensors: OrderedDict[str, Sensor]

    @property
    def num_acu(self) -> int:
        return len(self.acus.items())

    @property
    def num_ser(self) -> int:
        count = 0
        for rack in self.racks.values():
            for _ in rack.constructions.servers.values():
                count += 1
        return count

    @property
    def num_sen(self) -> int:
        return len(self.sensors.items())

    @property
    def acu_keys(self) -> List[str]:
        return list(self.acus.keys())

    @property
    def rack_keys(self) -> List[str]:
        return list(self.racks.keys())

    @property
    def server_keys(self) -> List[str]:
        server_key_list = []
        for rack in self.racks.values():
            for server_key, _ in rack.constructions.servers.items():
                server_key_list.append(server_key)
        return server_key_list

    @property
    def sensor_keys(self) -> List[str]:
        return list(self.sensors.keys())

    @property
    def servers(self) -> Dict[str, Server]:
        server_dict = {}
        for rack in self.racks.values():
            for server_id, server in rack.constructions.servers.items():
                server_dict[server_id] = server
        return server_dict

    @property
    def acu2sen(self) -> np.ndarray:
        """ Calculate the spatial distance matrix of the ACU to sensor connections
        """
        acu2sen_dis = np.zeros([self.num_acu, self.num_sen])
        for acu_idx, (acu_id, acu) in enumerate(self.acus.items()):
            for sen_idx, (sen_id, sen) in enumerate(self.sensors.items()):
                acu_loc = acu.geometry.location
                sen_loc = sen.geometry.location
                acu2sen_dis[acu_idx][sen_idx] = euclidean_distance(
                    loc_1=(acu_loc.x, acu_loc.y, acu_loc.z),
                    loc_2=(sen_loc.x, sen_loc.y, sen_loc.z),
                )
        return acu2sen_dis

    @property
    def ser2sen(self) -> np.ndarray:
        """ Calculate the spatial distance matrix of the server to sensor connections
        """
        ser2sen_dis = np.zeros([self.num_ser, self.num_sen])
        for rack_id, rack in self.racks.items():
            for ser_idx, (server_id, ser) in enumerate(rack.constructions.servers.items()):
                for sen_idx, (sen_id, sen) in enumerate(self.sensors.items()):
                    ser_loc_i, ser_loc_o = self.server_patch_positions(server_id)
                    sen_loc = sen.geometry.location
                    ser2sen_dis[ser_idx][sen_idx] = euclidean_distance(
                        loc_1=(ser_loc_o.x, ser_loc_o.y, ser_loc_o.z),
                        loc_2=(sen_loc.x, sen_loc.y, sen_loc.z),
                    )
        return ser2sen_dis

    @property
    def acu2ser(self) -> np.ndarray:
        """ Calculate the spatial distance matrix of the acu to server connections
        """
        acu2ser_dis = np.zeros([self.num_acu, self.num_ser])
        for acu_idx, (acu_id, acu) in enumerate(self.acus.items()):
            for rack_id, rack in self.racks.items():
                for ser_idx, (server_id, ser) in enumerate(rack.constructions.servers.items()):
                    acu_loc = acu.geometry.location
                    ser_loc, _ = self.server_patch_positions(server_id)
                    acu2ser_dis[acu_idx][ser_idx] = euclidean_distance(
                        loc_1=(acu_loc.x, acu_loc.y, acu_loc.z),
                        loc_2=(ser_loc.x, ser_loc.y, ser_loc.z),
                    )
        return acu2ser_dis

    def acu_patch_positions(self, acu_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of acu return and supply"""
        acu: ACU = self.acus.get(acu_id)

        def get_raw_point(face: ACUFace) -> Tuple[float, float, float]:
            if face.side == Face.front:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.rear:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.left:
                x = acu.geometry.location.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.right:
                x = acu.geometry.location.x + acu.geometry.size.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.y
            elif face.side == Face.top:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = acu.geometry.size.z
            elif face.side == Face.bottom:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = 0
            else:
                raise ValueError(f"not supported: face.side={face.side}")
            if self.raised_floor is not None:
                z += self.raised_floor.geometry.height
            return round(x, 3), round(y, 3), round(z, 3)

        def get_center_coordinate(face: ACUFace) -> Vertex:
            x, y, z = get_raw_point(face)
            x, y = rotate(
                (acu.geometry.location.x, acu.geometry.location.y), (x, y), acu.geometry.orientation
            )
            return Vertex(x=round(x, 3), y=round(y, 3), z=z)

        inlet = get_center_coordinate(acu.geometry.return_face)
        outlet = get_center_coordinate(acu.geometry.supply_face)

        return inlet, outlet

    def server_patch_positions(self, server_id: str) -> Tuple[Vertex, Vertex]:
        """Get the center point position of server inlet and outlet"""

        for rack_id, rack in self.racks.items():
            if server_id in rack.constructions.servers:
                server = rack.constructions.servers.get(server_id)
                server_rack = rack
                rack: Rack = server_rack

                z = rack.geometry.location.z + rack.geometry.first_slot_offset + 0.045 * (
                        server.geometry.slot_position - 1)
                z = round(z, 3)

                # inlet
                inlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                inlet_y = rack.geometry.location.y

                inlet_x, inlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y), (inlet_x, inlet_y), rack.geometry.orientation
                )
                inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

                # outlet
                outlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                outlet_y = rack.geometry.location.y + server.geometry.depth
                outlet_x, outlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y), (outlet_x, outlet_y), rack.geometry.orientation
                )
                outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y, 3), z=z)
                return inlet, outlet

        else:
            raise ValueError(f"Server {server_id} not found")


class Room(BaseModel):
    """ Room object in a data center
    """
    models: Optional[Model]
    inputs: Optional[Inputs] = Field(default_factory=Inputs)
    geometry: RoomGeometry
    constructions: Optional[RoomConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    @validator("constructions")
    def _validate_room_constructions(
        cls,
        room_construction: RoomConstruction,
        values: Dict
    ) -> RoomConstruction:
        cls._validate_acus(room_construction.acus, values["models"], values["inputs"])
        cls._validate_boxes(room_construction.boxes, values["models"])
        cls._validate_racks(room_construction.racks, values["models"], values["inputs"])
        cls._validate_sensors(room_construction.sensors)
        return room_construction

    @classmethod
    def _validate_acus(cls, acus: Dict, models: Model, inputs: Inputs) -> None:
        for acu_id, acu in acus.items():
            cls._validate_id(acu_id)
            cls._validate_geometry_models(acu, models.geometry_models.acus) if models.geometry_models else None
            cls._validate_cooling_models(acu, models.cooling_models.acus) if models.cooling_models.acus else None
            cls._validate_power_models(acu, models.power_models.acus) if models.power_models.acus else None
            cls._validate_inputs(acu, inputs.acus.get(acu_id)) if inputs.acus else None

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
        cls._validate_servers(rack, rack_constructions.servers, models, inputs)

    @classmethod
    def _validate_servers(cls, rack: Rack, servers: Dict, models: Model, inputs: Inputs) -> None:
        occupied_rack_slot = {}
        for server_id, server in servers.items():
            cls._validate_id(server_id)
            cls._validate_geometry_models(server, models.geometry_models.servers) if models.geometry_models else None
            cls._validate_cooling_models(server, models.cooling_models.servers) if models.cooling_models.servers else None
            cls._validate_power_models(server, models.power_models.servers) if models.power_models.servers else None
            cls._validate_inputs(server, inputs.servers.get(server_id)) if inputs.servers else None
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
        elif isinstance(obj, Server) and isinstance(inputs, ServerInputs):
            obj.power.input_power = inputs.input_power
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object inputs is not defined."
            )

    def dump(self, file_path: Union[str, Path]) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2))

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "Room":
        with open(file_path) as f:
            return cls(**json.load(f))
