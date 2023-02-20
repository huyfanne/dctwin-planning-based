from typing import OrderedDict

from dctwin.models.basics import Face, Size, Vertex
from pydantic import BaseModel


class ACUFace(BaseModel):
    side: Face
    width: float
    length: float
    offset: Vertex


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


class BoxFaces(BaseModel):
    top: bool
    bottom: bool
    front: bool
    rear: bool
    left: bool
    right: bool


class BoxModel(BaseModel):
    faces: BoxFaces


class RoomGeometryModel(BaseModel):
    acus: OrderedDict[str, ACUModel]
    racks: OrderedDict[str, RackModel]
    servers: OrderedDict[str, ServerModel]
    boxes: OrderedDict[str, BoxModel]
