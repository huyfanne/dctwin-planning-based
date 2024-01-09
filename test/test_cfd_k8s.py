from dctwin.interfaces import CFDManager
from dctwin.models.cfd import Room
from dctwin.utils import config

room = Room.load("models/geometry/room_test.json")
config.PRESERVE_FOAM_LOG = True
config._environ.__setitem__("is_local_k8s", "True")

manager = CFDManager(
    room=room,
    mesh_process=2,
    solve_process=2,
    is_k8s=True,
)
manager.run()
