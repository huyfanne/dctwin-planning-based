from dclib import Room
from dctwin.managers import CFDManager
from dctwin.utils import config

room = Room.load("test/models/geometry/k2test3_problem.json")
from pathlib import Path

room_json = "models/geometry/mesh_independence_sample_dh.json"

room = Room.load(room_json)
room_file_name = room_json.split("/")[-1].split(".")[0]

config.PRESERVE_FOAM_LOG = True

iterations = 500

# manager = CFDManager(room=room, mesh_process=8, solve_process=8, is_gpu=True, scale_server_flow_rate=True)
manager = CFDManager(
    room=room, 
    solve_process=6, 
    mesh_process=6, 
    is_gpu=False, 
    end_time=iterations
    )
manager.run()
