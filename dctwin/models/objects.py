from typing import Optional, OrderedDict

from dctwin.models.basics import Face, Size, Vertex
from dctwin.models.server import Server, ServerModel
from pydantic import BaseModel, Field, validator


class ObjectModel(BaseModel):
    size: Optional[Size]
    placement: Vertex


class ACUFace(BaseModel):
    side: Face
    width: float
    length: float
    offset: Vertex


class ACUModel(BaseModel):
    size: Size
    supply_face: ACUFace
    return_face: ACUFace


class ACU(ObjectModel):
    id: str
    model: str = ""
    orientation: int
    supply_temperature: float
    flow_rate: float
    supply_face: Optional[Face]
    return_face: Optional[Face]
    meta: OrderedDict = Field(default_factory=dict)

    def calculate_face_area(self, face: Face) -> float:
        if face in (Face.front, Face.rear):
            return self.size.dx / 2 * self.size.dz / 2
        if face in (Face.left, Face.right):
            return self.size.dx / 2 * self.size.dz / 2
        if face in (Face.bottom, Face.top):
            return self.size.dx / 2 * self.size.dz / 2
        raise ValueError(f"No such face: {face}")

    @property
    def supply_area(self):
        return self.calculate_face_area(self.supply_face)

    @property
    def return_area(self):
        return self.calculate_face_area(self.return_face)

    @property
    def k(self) -> float:
        """turbulent kinetic energy
        Others:
        omega = epsilon / (0.09 * k)
        """
        tu = 0.1
        u = float(self.flow_rate / self.supply_area)
        k = 1.5 * ((tu / 100) ** 2) * (u ** 2)
        return k

    @property
    def epsilon(self) -> float:
        """
        turbulent dissipation rate
        """
        nu = 1.5e-05
        eddy_viscosity_ratio = 10
        return 0.09 * (self.k ** 2) / (nu * eddy_viscosity_ratio)


class RackModel(BaseModel):
    first_slot_offset: float
    slot: int
    size: Size


class Rack(ObjectModel):
    id: str
    model: str
    orientation: int
    has_blanking_panel: Optional[bool]


class Sensor(Vertex):
    id: str
    meta: OrderedDict = Field(default_factory=dict)


# noinspection PyMethodParameters
class Objects(BaseModel):
    rack_models: OrderedDict[str, RackModel]
    acu_models: OrderedDict[str, ACUModel]
    server_models: OrderedDict[str, ServerModel]
    acus: OrderedDict[str, ACU]
    racks: OrderedDict[str, Rack]
    servers: OrderedDict[str, Server]

    sensors: OrderedDict[str, Sensor] = Field(default_factory=dict)

    def rack_model(self, rack_id):
        return self.rack_models[self.racks[rack_id].model]

    @classmethod
    def _validate_id(cls, v: dict):
        for _id, obj in v.items():
            if not _id.isidentifier():
                raise ValueError(f"must be valid identifier: {_id}")
            obj["id"] = _id
        return v

    @validator("acus", pre=True)
    def validate_acus_pre(cls, v):
        return cls._validate_id(v)

    @validator("racks", pre=True)
    def validate_racks_pre(cls, v):
        return cls._validate_id(v)

    @validator("servers", pre=True)
    def validate_servers_pre(cls, v):
        return cls._validate_id(v)

    @validator("sensors", pre=True)
    def validate_sensors(cls, v):
        return cls._validate_id(v)

    @validator("acus")
    def validate_acus(cls, v, values):
        for acu in v.values():
            acu_model = values["acu_models"][acu.model]
            acu.supply_face = acu_model.supply_face.side
            acu.return_face = acu_model.return_face.side
            acu.size = acu_model.size
        return v

    @validator("racks")
    def validate_racks(cls, v, values):
        for rack in v.values():
            rack_model = values["rack_models"][rack.model]
            rack.size = rack_model.size
        return v

    @validator("servers")
    def validate_servers(cls, v, values):
        all_slots = dict()
        for server in v.values():
            server_model = values["server_models"][server.model]
            server.occupation = server_model.occupation

            rack = values["racks"].get(server.rack_id)
            if rack is None:
                raise ValueError(
                    f"invalid rack id: {server.rack_id} in Server({server.id})"
                )
            rack_model = values["rack_models"][rack.model]
            if server.slot < 1 or server.slot + server.occupation > rack_model.slot + 1:
                raise ValueError(
                    f"invalid server slot/occupation: "
                    f"Server({server.id}, slot={server.slot}, "
                    f"occupation={server.occupation})"
                )
            if server.rack_id not in all_slots:
                all_slots[rack.id] = dict()

            for i in range(server.slot, server.slot + server.occupation):
                if i not in all_slots[server.rack_id]:
                    all_slots[server.rack_id][i] = server.id
                else:
                    raise ValueError(
                        f"invalid server slot/occupation: "
                        f"Server({server.id}) has collision with "
                        f"Server({all_slots[server.rack_id][i]})"
                    )

        return v
