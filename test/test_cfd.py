from dclib import Room
from dctwin.managers import CFDManager
from dctwin.utils import config

room = Room.load("test/models/geometry/k2_project.json")
config.PRESERVE_FOAM_LOG = True

iterations = 500

# manager = CFDManager(room=room, mesh_process=8, solve_process=8, is_gpu=True, scale_server_flow_rate=True)
manager = CFDManager(
    room=room, 
    solve_process=2, 
    mesh_process=2, 
    is_gpu=False, 
    end_time=iterations
    )
manager.run()
