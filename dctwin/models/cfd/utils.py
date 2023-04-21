import math
from typing import Tuple
from .basics import Vertex


def euclidean_distance(loc_1: Vertex, loc_2: Vertex) -> float:
    return math.sqrt((loc_1.x - loc_2.x) ** 2 + (loc_1.y - loc_2.y) ** 2 + (loc_1.z - loc_2.z) ** 2)


def rotate(origin: Tuple[float, float], point: Tuple[float, float], angle: int) -> Tuple[float, float]:
    ox, oy = origin
    px, py = point
    _angle = angle / 180 * math.pi
    qx = ox + math.cos(_angle) * (px - ox) - math.sin(_angle) * (py - oy)
    qy = oy + math.sin(_angle) * (px - ox) + math.cos(_angle) * (py - oy)
    return qx, qy


def camel_to_snake(name):
    """Convert a camel case string to snake case"""
    snake = ""
    for char in name:
        if char.isupper():
            snake += "_" + char.lower()
        else:
            snake += char
    return snake


def convert_key_to_snake(data):
    """Convert a dictionary's outermost layer keys from camel case to snake case"""
    if isinstance(data, dict):
        snake_dict = {}
        for key, value in data.items():
            snake_key = camel_to_snake(key)
            snake_dict[snake_key] = value
        return snake_dict
    else:
        return data


def convert_json_file(data):
    """Convert specific JSON attribute from camel case to snake case"""
    snake_data = convert_key_to_snake(data)
    try:
        snake_data["models"] = convert_key_to_snake(snake_data["models"])
        for key, value in snake_data["models"]["geometry_models"]["acus"].items():
            snake_data["models"]["geometry_models"]["acus"][key] = convert_key_to_snake(value)
        for key, value in snake_data["models"]["geometry_models"]["racks"].items():
            snake_data["models"]["geometry_models"]["racks"][key] = convert_key_to_snake(value)
        for key, value in snake_data["models"]["geometry_models"]["servers"].items():
            snake_data["models"]["geometry_models"]["servers"][key] = convert_key_to_snake(value)
    except KeyError:
        pass
    try:
        for key, value in snake_data["inputs"]["acus"].items():
            snake_data["inputs"]["acus"][key] = convert_key_to_snake(value)
        for key, value in snake_data["inputs"]["servers"].items():
            snake_data["inputs"]["servers"][key] = convert_key_to_snake(value)
    except KeyError:
        pass
    for room_key, room_value in snake_data["constructions"]["rooms"].items():
        snake_data["constructions"]["rooms"][room_key]["geometry"] = convert_key_to_snake(room_value["geometry"])
        snake_data["constructions"]["rooms"][room_key]["constructions"] = convert_key_to_snake(room_value["constructions"])
        for rack_key, rack_value in room_value["constructions"]["racks"].items():
            snake_data["constructions"]["rooms"][room_key]["constructions"]["racks"][rack_key]["geometry"] = convert_key_to_snake(rack_value["geometry"])
            for server_key, server in rack_value["constructions"]["servers"].items():
                snake_data["constructions"]["rooms"][room_key]["constructions"]["racks"][rack_key]["constructions"]["servers"][server_key][
                    "geometry"] = convert_key_to_snake(server["geometry"])
    return snake_data
