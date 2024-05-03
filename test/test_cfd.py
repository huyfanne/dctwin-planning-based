from dclib import Room
from dctwin.interfaces import CFDManager
from dctwin.utils import config

room = Room.load("models/geometry/acs_level_5_test_v2.json")
config.PRESERVE_FOAM_LOG = True

iterations = 50

# manager = CFDManager(room=room, mesh_process=2, solve_process=2, is_gpu=True)
manager = CFDManager(room=room, mesh_process=2, solve_process=2, is_gpu=False)
manager.run()
