from dclib import Room
from dctwin.managers import CFDManager
from dctwin.utils import config
from pathlib import Path

room_json = "models/geometry/room_test_heat_emitting.json"

room = Room.load(room_json)
room_file_name = room_json.split("/")[-1].split(".")[0]

config.PRESERVE_FOAM_LOG = True

next_index = len(
    [d for d in Path("log").iterdir() if d.name.startswith(f"{room_file_name}_")]
)

config.LOG_DIR = Path(f"log/{room_file_name}_{next_index}").absolute()

iterations = 500

# manager = CFDManager(room=room, mesh_process=8, solve_process=8, is_gpu=True, scale_server_flow_rate=True)
manager = CFDManager(
    room=room,
    solve_process=2,
    mesh_process=2,
    is_gpu=False,
    end_time=iterations,
    # only_save_latest=False,
    # write_interval=10
)
manager.run()

foam_old_path = Path(f"log/{room_file_name}_{next_index}/base/case.foam")
foam_new_path = Path(
    f"log/{room_file_name}_{next_index}/base/{room_file_name}_{next_index}.foam"
)

if foam_old_path.exists():
    foam_old_path.replace(foam_new_path)
else:
    print("CFD simulation failed")
