import math
from typing import Tuple
from pydantic import BaseModel as PydanticBaseModel


def rotate(origin: Tuple[float, float], point: Tuple[float, float], angle: int) -> Tuple[float, float]:
    ox, oy = origin
    px, py = point
    _angle = angle / 180 * math.pi
    qx = ox + math.cos(_angle) * (px - ox) - math.sin(_angle) * (py - oy)
    qy = oy + math.sin(_angle) * (px - ox) + math.cos(_angle) * (py - oy)
    return qx, qy


def to_camel(string: str) -> str:
    words = string.split('_')
    return words[0] + ''.join(word.capitalize() for word in words[1:])


class BaseModel(PydanticBaseModel):
    class Config:
        alias_generator = to_camel
