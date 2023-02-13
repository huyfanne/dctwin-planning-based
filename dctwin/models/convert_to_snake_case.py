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
    for key, value in snake_data["geometry_model"]["acus"].items():
        snake_data["geometry_model"]["acus"][key] = convert_key_to_snake(value)
    for key, value in snake_data["geometry_model"]["racks"].items():
        snake_data["geometry_model"]["racks"][key] = convert_key_to_snake(value)
    for key, value in snake_data["geometry_model"]["servers"].items():
        snake_data["geometry_model"]["servers"][key] = convert_key_to_snake(value)
    snake_data["constructions"] = convert_key_to_snake(snake_data["constructions"])
    for key, value in snake_data["constructions"]["racks"].items():
        snake_data["constructions"]["racks"][key]["geometry"] = convert_key_to_snake(value["geometry"])
        for server_key, server in value["constructions"]["servers"].items():
            snake_data["constructions"]["racks"][key]["constructions"]["servers"][server_key]["geometry"] = convert_key_to_snake(server["geometry"])
    for key, value in snake_data["inputs"]["acus"].items():
        snake_data["inputs"]["acus"][key] = convert_key_to_snake(value)
    for key, value in snake_data["inputs"]["servers"].items():
        snake_data["inputs"]["servers"][key] = convert_key_to_snake(value)
    return  snake_data

