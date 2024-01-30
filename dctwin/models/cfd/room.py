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
    """RoomConstruction is used to build the objects in a room"""

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
    def num_rack(self) -> int:
        return len(self.racks.items())

    @property
    def num_ser(self) -> int:
        count = 0
        for _, rack in self.racks.items():
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
        for _, rack in self.racks.items():
            for server_key, _ in rack.constructions.servers.items():
                server_key_list.append(server_key)
        return server_key_list

    @property
    def sensor_keys(self) -> List[str]:
        return list(self.sensors.keys())

    @property
    def servers(self) -> Dict[str, Server]:
        server_dict = {}
        for _, rack in self.racks.items():
            for server_id, server in rack.constructions.servers.items():
                server_dict[server_id] = server
        return server_dict

    @property
    def acu2sen(self) -> np.ndarray:
        """Calculate the spatial distance matrix of the ACU inlet to sensor connections"""
        acu2sen_dis = np.zeros([self.num_acu, self.num_sen])
        for acu_idx, (acu_id, acu) in enumerate(self.acus.items()):
            for sen_idx, (sen_id, sen) in enumerate(self.sensors.items()):
                acu_return, acu_supply, acu_center = self.acu_patch_positions(acu_id)
                sen_loc = sen.geometry.location
                acu2sen_dis[acu_idx][sen_idx] = euclidean_distance(
                    loc_1=(acu_center.x, acu_center.y, acu_center.z),
                    loc_2=(sen_loc.x, sen_loc.y, sen_loc.z),
                )
        return acu2sen_dis

    @property
    def acu2ser(self) -> np.ndarray:
        """Calculate the spatial distance matrix of the ACU inlet to server connections"""
        acu2ser_dis = np.zeros([self.num_acu, self.num_ser])
        for acu_idx, (acu_id, acu) in enumerate(self.acus.items()):
            ser_idx: int = 0
            for rack_id, rack in self.racks.items():
                for server_id, ser in rack.constructions.servers.items():
                    acu_return, acu_supply, acu_center = self.acu_patch_positions(
                        acu_id
                    )
                    ser_inlet, ser_outlet, ser_center = self.server_patch_positions(
                        server_id
                    )
                    acu2ser_dis[acu_idx][ser_idx] = euclidean_distance(
                        loc_1=(acu_center.x, acu_center.y, acu_center.z),
                        loc_2=(ser_center.x, ser_center.y, ser_center.z),
                    )
                    ser_idx += 1
        return acu2ser_dis

    @property
    def acu2rack(self) -> np.ndarray:
        """Calculate the spatial distance matrix of the ACU inlet to rack"""
        acu2rack_dis = np.zeros([self.num_acu, self.num_rack])
        for acu_idx, (acu_id, acu) in enumerate(self.acus.items()):
            rack_idx: int = 0
            for rack_id, rack in self.racks.items():
                acu_return, acu_supply, acu_center = self.acu_patch_positions(acu_id)
                rack_inlet, rack_outlet, rack_center = self.rack_patch_positions(
                    rack_id
                )
                acu2rack_dis[acu_idx][rack_idx] = euclidean_distance(
                    loc_1=(acu_center.x, acu_center.y, acu_center.z),
                    loc_2=(rack_center.x, rack_center.y, rack_center.z),
                )
                rack_idx += 1
        return acu2rack_dis

    @property
    def rack2acu(self) -> np.ndarray:
        """Calculate the spatial distance matrix of the ACU inlet to rack"""
        rack2acu_dis = np.zeros([self.num_rack, self.num_acu])
        for rack_idx, (rack_id, rack) in enumerate(self.racks.items()):
            acu_idx: int = 0
            for acu_id, acu in self.acus.items():
                rack_inlet, rack_outlet, rack_center = self.rack_patch_positions(
                    rack_id
                )
                acu_return, acu_supply, acu_center = self.acu_patch_positions(acu_id)
                rack2acu_dis[rack_idx][acu_idx] = euclidean_distance(
                    loc_1=(rack_center.x, rack_center.y, rack_center.z),
                    loc_2=(acu_center.x, acu_center.y, acu_center.z),
                )
                acu_idx += 1
        return rack2acu_dis

    @property
    def ser2sen(self) -> np.ndarray:
        """Calculate the spatial distance matrix of the server outlet to sensor connections"""
        ser2sen_dis = np.zeros([self.num_ser, self.num_sen])
        ser_idx: int = 0
        for rack_id, rack in self.racks.items():
            for server_id, ser in rack.constructions.servers.items():
                for sen_idx, (sen_id, sen) in enumerate(self.sensors.items()):
                    ser_inlet, ser_outlet, ser_center = self.server_patch_positions(
                        server_id
                    )
                    sen_loc = sen.geometry.location
                    ser2sen_dis[ser_idx][sen_idx] = euclidean_distance(
                        loc_1=(ser_center.x, ser_center.y, ser_center.z),
                        loc_2=(sen_loc.x, sen_loc.y, sen_loc.z),
                    )
                ser_idx += 1
        return ser2sen_dis

    def rack_patch_positions(self, rack_id: str) -> Tuple[Vertex, Vertex, Vertex]:
        """Get the coordinate of rack inlet, outlet and center"""

        try:
            rack: Rack = self.racks.get(rack_id)

            z = rack.geometry.location.z + rack.geometry.first_slot_offset
            z = round(z, 3)

            # inlet
            inlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
            inlet_y = rack.geometry.location.y
            inlet_x, inlet_y = rotate(
                (rack.geometry.location.x, rack.geometry.location.y),
                (inlet_x, inlet_y),
                rack.geometry.orientation,
            )
            inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

            # outlet
            outlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
            outlet_y = rack.geometry.location.y
            outlet_x, outlet_y = rotate(
                (rack.geometry.location.x, rack.geometry.location.y),
                (outlet_x, outlet_y),
                rack.geometry.orientation,
            )
            outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y, 3), z=z)

            # center
            center_x = rack.geometry.location.x + rack.geometry.size.x / 2
            center_y = rack.geometry.location.y
            center_x, center_y = rotate(
                (rack.geometry.location.x, rack.geometry.location.y),
                (center_x, center_y),
                rack.geometry.orientation,
            )
            center = Vertex(x=round(center_x, 3), y=round(center_y, 3), z=z)
            return inlet, outlet, center

        except:
            raise ValueError(f"Rack positions not found")

    def acu_patch_positions(self, acu_id: str) -> Tuple[Vertex, Vertex, Vertex]:
        """Get the coordinate of acu return, supply and center"""
        acu: ACU = self.acus.get(acu_id)

        def get_center_point_by_face(face: ACUFace) -> Tuple[float, float, float]:
            if face.side == Face.front:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.z
            elif face.side == Face.rear:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.z
            elif face.side == Face.left:
                x = acu.geometry.location.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.z
            elif face.side == Face.right:
                x = acu.geometry.location.x + acu.geometry.size.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 - face.offset.x
                z = acu.geometry.location.z + acu.geometry.size.z / 2 + face.offset.z
            elif face.side == Face.top:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = acu.geometry.location.z + acu.geometry.size.z
            elif face.side == Face.bottom:
                x = acu.geometry.location.x + acu.geometry.size.x / 2 + face.offset.x
                y = acu.geometry.location.y + acu.geometry.size.y / 2 + face.offset.y
                z = acu.geometry.location.z
            else:
                raise ValueError(f"not supported: face.side={face.side}")
            return round(x, 3), round(y, 3), round(z, 3)

        def get_center_coordinate(face: ACUFace = None) -> Vertex:
            if face is not None:
                x, y, z = get_center_point_by_face(face)
            else:
                x = acu.geometry.location.x + acu.geometry.size.x / 2
                y = acu.geometry.location.y + acu.geometry.size.y / 2
                z = acu.geometry.location.z + acu.geometry.size.z / 2
            x, y = rotate(
                (acu.geometry.location.x, acu.geometry.location.y),
                (x, y),
                acu.geometry.orientation,
            )
            return Vertex(x=round(x, 3), y=round(y, 3), z=z)

        return_center = get_center_coordinate(acu.geometry.return_face)
        supply_center = get_center_coordinate(acu.geometry.supply_face)
        center = get_center_coordinate()

        return return_center, supply_center, center

    def server_patch_positions(self, server_id: str) -> Tuple[Vertex, Vertex, Vertex]:
        """Get the coordinate of server inlet, outlet and center"""

        for rack_id, rack in self.racks.items():
            if server_id in rack.constructions.servers:
                server = rack.constructions.servers.get(server_id)
                server_rack = rack
                rack: Rack = server_rack

                z = (
                    rack.geometry.location.z
                    + rack.geometry.first_slot_offset
                    + 0.045
                    * (
                        server.geometry.slot_position
                        + server.geometry.slot_occupation / 2
                        - 1
                    )
                )
                z = round(z, 3)

                # inlet
                inlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                inlet_y = rack.geometry.location.y
                inlet_x, inlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y),
                    (inlet_x, inlet_y),
                    rack.geometry.orientation,
                )
                inlet = Vertex(x=round(inlet_x, 3), y=round(inlet_y, 3), z=z)

                # outlet
                outlet_x = rack.geometry.location.x + rack.geometry.size.x / 2
                outlet_y = rack.geometry.location.y + server.geometry.depth
                outlet_x, outlet_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y),
                    (outlet_x, outlet_y),
                    rack.geometry.orientation,
                )
                outlet = Vertex(x=round(outlet_x, 3), y=round(outlet_y, 3), z=z)

                # center
                center_x = rack.geometry.location.x + rack.geometry.size.x / 2
                center_y = rack.geometry.location.y + server.geometry.depth / 2
                center_x, center_y = rotate(
                    (rack.geometry.location.x, rack.geometry.location.y),
                    (center_x, center_y),
                    rack.geometry.orientation,
                )
                center = Vertex(x=round(center_x, 3), y=round(center_y, 3), z=z)
                return inlet, outlet, center

        else:
            raise ValueError(f"Server {server_id} not found")


class Room(BaseModel):
    """Room object in a data center"""

    models: Model = Field(default_factory=Model)
    inputs: Inputs = Field(default_factory=Inputs)
    geometry: RoomGeometry
    constructions: RoomConstruction = Field(default_factory=RoomConstruction)
    meta: Optional[OrderedDict] = Field(default_factory=dict)

    @validator("constructions")
    def _validate_room_constructions(
        cls, room_construction: RoomConstruction, values: Dict
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
            cls._validate_geometry_models(
                acu, models.geometry_models.acus
            ) if models.geometry_models else None
            cls._validate_cooling_models(
                acu, models.cooling_models.acus
            ) if models.cooling_models.acus else None
            cls._validate_power_models(
                acu, models.power_models.acus
            ) if models.power_models.acus else None
            cls._validate_inputs(acu, inputs.acus.get(acu_id)) if inputs.acus else None

    @classmethod
    def _validate_boxes(cls, boxes: Dict, models: Model) -> None:
        for box_id, box in boxes.items():
            cls._validate_id(box_id)
            cls._validate_geometry_models(
                box, models.geometry_models.boxes
            ) if models.geometry_models else None

    @classmethod
    def _validate_racks(cls, racks: Dict, models: Model, inputs: Inputs) -> None:
        all_servers, invalid_occupation = {}, {}
        for rack_id, rack in racks.items():
            cls._validate_id(rack_id)
            cls._validate_geometry_models(
                rack, models.geometry_models.racks
            ) if models.geometry_models else None
            cls._validate_rack_constructions(
                rack,
                rack.constructions,
                all_servers,
                invalid_occupation,
                models,
                inputs,
            )
        if invalid_occupation:
            msg = f"Server collision error:"
            for server_a, server_b in invalid_occupation.items():
                msg += f"\n{server_a} collides with {server_b}"
            raise ValueError(f"{msg}")

    @classmethod
    def _validate_rack_constructions(
        cls,
        rack: Rack,
        rack_constructions: RackConstruction,
        all_servers: Dict,
        invalid_occupation: Dict,
        models: Model,
        inputs: Inputs,
    ) -> None:
        cls._validate_servers(
            rack,
            rack_constructions.servers,
            all_servers,
            invalid_occupation,
            models,
            inputs,
        )

    @classmethod
    def _validate_servers(
        cls,
        rack: Rack,
        servers: Dict,
        all_server: Dict,
        invalid_occupation: Dict,
        models: Model,
        inputs: Inputs,
    ) -> None:
        occupied_rack_slot = {}
        for server_id, server in servers.items():
            if server_id not in all_server:
                cls._validate_id(server_id)
                cls._validate_geometry_models(
                    server, models.geometry_models.servers
                ) if models.geometry_models else None
                cls._validate_cooling_models(
                    server, models.cooling_models.servers
                ) if models.cooling_models.servers else None
                cls._validate_power_models(
                    server, models.power_models.servers
                ) if models.power_models.servers else None
                cls._validate_inputs(
                    server, inputs.servers.get(server_id)
                ) if inputs.servers else None
                cls._validate_server_occupation(
                    rack, server, server_id, occupied_rack_slot, invalid_occupation
                )
                all_server[server_id] = server
            else:
                raise ValueError(f"Server {server_id} is duplicated")

    @classmethod
    def _validate_server_occupation(
        cls,
        rack: Rack,
        server: Server,
        server_id: str,
        occupied_rack_slot: Dict,
        invalid_occupation: Dict,
    ) -> None:
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
                invalid_occupation[server_id] = occupied_rack_slot[i]

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
        cls, obj: Union[ACU, Server, Rack, Box], models: Dict
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
            obj.geometry.faces = models.get(model_name).faces
        elif isinstance(obj, Server) and models is not None:
            obj.geometry.slot_occupation = models.get(model_name).slot_occupation
            obj.geometry.width = models.get(model_name).width
            obj.geometry.depth = models.get(model_name).depth
            obj.geometry.inlet_face = models.get(model_name).inlet_face
            obj.geometry.outlet_face = models.get(model_name).outlet_face
        elif isinstance(obj, Box) and models is not None:
            obj.geometry.faces = models.get(model_name).faces
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object geometry model is not defined."
            )

    @classmethod
    def _validate_power_models(cls, obj: Union[ACU, Server], models: Dict) -> None:
        model_name = obj.power.model
        if isinstance(obj, ACU) and models is not None:
            obj.power.rated_fan_power = models.get(model_name).rated_fan_power
        elif isinstance(obj, Server) and models is not None:
            obj.power.rated_power = models.get(model_name).rated_power
        else:
            raise ValueError(
                f"Invalid object type: {type(obj)}: "
                f"The object power model is not defined."
            )

    @classmethod
    def _validate_cooling_models(cls, obj: Union[ACU, Server], models: Dict) -> None:
        model_name = obj.cooling.model
        if isinstance(obj, ACU) and models is not None:
            obj.cooling.cooling_type = models.get(model_name).cooling_type
            obj.cooling.cooling_capacity = models.get(model_name).cooling_capacity
        elif isinstance(obj, Server) and models is not None:
            obj.cooling.fan_type = models.get(model_name).fan_type
            obj.cooling.volume_flow_rate_ratio = models.get(
                model_name
            ).volume_flow_rate_ratio
            obj.cooling.volume_flow_rate = models.get(model_name).volume_flow_rate
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

    def dump(self, file_path: Union[str, Path], by_alias: bool = True) -> None:
        with open(file_path, "w") as f:
            f.write(self.json(indent=2, by_alias=by_alias))

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "Room":
        with open(file_path) as f:
            return cls(**json.load(f))
