from dclib import Room
from dctwin.interfaces import CFDManager
from dctwin.utils import config

room = Room.load("/home/azureuser/dctwin/test/models/geometry/custom/ACS Level 4 Data Hall scenario 4 engine 1.6.6 use GPU.json")
config.PRESERVE_FOAM_LOG = True

iterations = 50

manager = CFDManager(room=room, mesh_process=8, solve_process=8, is_gpu=True, scale_server_flow_rate=True)
# manager = CFDManager(room=room, mesh_process=2, solve_process=2, is_gpu=False)
manager.run()
