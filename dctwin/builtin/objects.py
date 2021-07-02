from dctwin.models import Size, Vertex
from dctwin.models.objects import ACUModel, ACUFace, RackModel
from dctwin.models.server import ServerModel

acu_model_1 = ACUModel(
    size=Size(dx=1.6, dy=0.8, dz=2),
    supply_face=ACUFace(side='front',
                        width=1.4,
                        length=1.8,
                        offset=Vertex(x=0, y=0, z=0)),
    return_face=ACUFace(side='top',
                        width=1.4,
                        length=0.8,
                        offset=Vertex(x=0, y=0, z=0)),
)

rack_model_1 = RackModel(
    first_slot_offset=0.1,
    slot=42,
    size=Size(dx=0.6, dy=1.2, dz=2.2),
)

server_4u = ServerModel(
    occupation=4,
    depth=0.6,
)
