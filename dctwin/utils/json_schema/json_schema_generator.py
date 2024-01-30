import json
from dclib.room import Room

<<<<<<< HEAD
schema = Room.model_json_schema()
with open('room_schema.json', 'w') as f:
=======
schema = Room.schema()
with open("room_schema.json", "w") as f:
>>>>>>> main
    json.dump(schema, f, indent=2)
