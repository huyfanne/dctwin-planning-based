from typing import OrderedDict

from ..basics import Size, ACUFace, BoxFaces
from pydantic import BaseModel


class ACUModel(BaseModel):
    size: Size
    supply_face: ACUFace
    return_face: ACUFace


class RackModel(BaseModel):
    first_slot_offset: float
    slot: int
    size: Size


class ServerModel(BaseModel):
    slot_occupation: int
    depth: float
    width: float


class BoxModel(BaseModel):
    faces: BoxFaces


class RoomGeometryModel(BaseModel):
    acus: OrderedDict[str, ACUModel]
    racks: OrderedDict[str, RackModel]
    servers: OrderedDict[str, ServerModel]
    boxes: OrderedDict[str, BoxModel]


