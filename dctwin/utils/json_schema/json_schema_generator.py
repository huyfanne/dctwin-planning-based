import json
from dclib.room import Room

schema = Room.model_json_schema()
with open("room_schema.json", "w") as f:
    json.dump(schema, f, indent=2)
