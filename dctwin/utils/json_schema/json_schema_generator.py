import json
from dctwin.models.objects import Room

schema = Room.schema()
with open('room_schema.json', 'w') as f:
    json.dump(schema, f, indent=2)
