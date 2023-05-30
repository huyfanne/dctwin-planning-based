from dctwin.interfaces import CFDManager
from dctwin.models.cfd import Room
from dctwin.utils import config
from pathlib import Path
config.CASE_DIR = Path("log/tmp").absolute()
room = Room.load("model/geometry/room_new.json")
config.PRESERVE_FOAM_LOG = True
manager = CFDManager(room=room)
# bd = manager.room.format_boundary_conditions
manager.run()