import math
from typing import Tuple


def rotate(origin: Tuple[float, float], point: Tuple[float, float], angle: int) -> Tuple[float, float]:
    ox, oy = origin
    px, py = point
    _angle = angle / 180 * math.pi
    qx = ox + math.cos(_angle) * (px - ox) - math.sin(_angle) * (py - oy)
    qy = oy + math.sin(_angle) * (px - ox) + math.cos(_angle) * (py - oy)
    return qx, qy
