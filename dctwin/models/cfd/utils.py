import math
from typing import Tuple
from pydantic import BaseModel as PydanticBaseModel


def euclidean_distance(
    loc_1: Tuple[float, float, float], loc_2: Tuple[float, float, float]
) -> float:
    x_1, y_1, z_1 = loc_1
    x_2, y_2, z_2 = loc_2
    return math.sqrt((x_1 - x_2) ** 2 + (y_1 - y_2) ** 2 + (z_1 - z_2) ** 2)


def rotate(
    origin: Tuple[float, float], point: Tuple[float, float], angle: int
) -> Tuple[float, float]:
    ox, oy = origin
    px, py = point
    _angle = angle / 180 * math.pi
    qx = ox + math.cos(_angle) * (px - ox) - math.sin(_angle) * (py - oy)
    qy = oy + math.sin(_angle) * (px - ox) + math.cos(_angle) * (py - oy)
    return qx, qy


def to_camel(string: str) -> str:
    words = string.split("_")
    return words[0] + "".join(word.capitalize() for word in words[1:])


class BaseModel(PydanticBaseModel):
    class Config:
        alias_generator = to_camel
