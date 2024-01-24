from dctwin.interfaces import CFDManager
from dctwin.models.cfd import Room
from dctwin.utils import config

room = Room.load("models/geometry/room_test.json")
config.PRESERVE_FOAM_LOG = True

manager = CFDManager(room=room, mesh_process=2, solve_process=2)
manager.run()
