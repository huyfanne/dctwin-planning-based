def convert_pillars(arr):
    pillars = {}
    for item in arr:
        pillars[item['id']] = {
            'id': item['id'],
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            'placement': item['location'],
        }
    return pillars


def convert_containments(arr):
    containments = {}
    for item in arr:
        containments[item['id']] = {
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            'placement': item['location'],
            "front": item['faces'][0],
            "rear": item['faces'][1],
            "left": item['faces'][2],
            "right": item['faces'][3],
            "top": item['faces'][4],
            "bottom": item['faces'][5],
        }
    return containments


def convert_floor(obj):
    if obj is None:
        return None
    final_obj = {
        "height": obj['height'],
        "opening_list": [],
    }
    for item in obj["openingLists"]:
        final_obj["opening_list"].append({
            "placement": item['location'],
            "size": {
                "dx": item['size']['x'],
                "dy": item['size']['y'],
                "dz": item['size']['z']
            },
        })

    return final_obj


def convert_ceiling(obj):
    if obj is None:
        return None
    final_obj = {
        "height": obj['height'],
        "duct_list": [],
    }
    for item in obj["openingLists"]:
        final_obj["duct_list"].append({
            "placement": item['location'],
            "size": {
                "dx": item['size']['x'],
                "dy": item['size']['y'],
                "dz": item['size']['z']
            },
        })

    return final_obj


def convert_rack_models(arr):
    rack_models = {}
    for item in arr:
        rack_models[item['modelName']] = {
            "first_slot_offset": item['firstSlotOffset'],
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            "slot": item['slot']
        }
    return rack_models


def convert_acu_models(arr):
    acu_models = {}
    for item in arr:
        acu_models[item['modelName']] = {
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            "supply_face": item['supplyFace'],
            "return_face": item['returnFace'],
        }
    return acu_models


def convert_server_models(arr):
    server_models = {}
    for item in arr:
        server_models[item['modelName']] = {
            "occupation": item['slotOccupation'],
            "depth": item['depth'],
            # todo: check on missing slot attribute
            # "width"
        }
    return server_models


def convert_acus(arr):
    acus = {}
    for item in arr:
        acus[item['id']] = {
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            "placement": item['location'],
            "id": item['id'],
            "model": item['modelName'],
            "supply_temperature": item['supplyTemperature'],
            "flow_rate": item['supplyAirFlowRate'],
            "orientation": item['orientation'],
            "supply_face": item['supplyFace']['side'],
            "return_face": item['returnFace']['side']
        }
    return acus


def convert_racks(arr):
    racks = {}
    for item in arr:
        racks[item['id']] = {
            'size': {
                'dx': item['size']['x'],
                'dy': item['size']['y'],
                'dz': item['size']['z']
            },
            "placement": item['location'],
            "id": item['id'],
            "model": item['modelName'],
            "has_blanking_panel": item['hasBlankingPanel'],
            "orientation": item['orientation']
        }
    return racks


def convert_servers(arr):
    servers = {}
    for item in arr:
        servers[item['id']] = {
            "id": item['id'],
            "model": item['modelName'],
            "slot": item['slotPosition'],
            "occupation": item['slotOccupation'],
            "heat_load": item['heatLoad'],
            "flow_rate": item['flowRate'],
            "width": item['width'],
            "rack_id": item['parent'],
            "orientation": item['orientation']
        }
    return servers


def convert_sensors(arr):
    sensors = {}
    for item in arr:
        sensors[item['id']] = {
            "id": item['id'],
            "meta": item['meta'],
            **item['location'],
        }
    return sensors


def convert_json(room):
    data = room
    final_data = {
        "name": data["name"],
        "height": data["geometry"]["height"],
        "version": "0.32",
        "plane_outline": data["geometry"]["plane"],
        "constructions": {
            "partition_walls": convert_pillars(data["constructions"]["partitions"]),
            "pillars": convert_pillars(data["constructions"]["pillars"]),
            "containments": convert_containments(data["constructions"]["containments"]),
            "raised_floor": convert_floor(data["constructions"]["raisedFloor"]),
            "ceiling": convert_ceiling(data["constructions"]["falseCeiling"]),
        },
        "objects": {
            "rack_models": convert_rack_models(data["models"]["rackModel"]),
            "acu_models": convert_acu_models(data["models"]["acuModel"]),
            "server_models": convert_server_models(data["models"]["serverModel"]),
            "acus": convert_acus(data["objects"]["acus"]),
            "racks": convert_racks(data["objects"]["racks"]),
            "servers": convert_servers(data["objects"]["servers"]),
            "sensors": convert_sensors(data["objects"]["sensors"]),
        }
    }
    return final_data
