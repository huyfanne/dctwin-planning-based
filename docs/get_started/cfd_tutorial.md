In this case, we will conduct a CFD simulation for a data center with one CRAC unit and 20 racks without containment.

(1) Configure environment variable (log save dir) and read room geometry file
``` py linenums="1"
config.CASE_DIR = Path("log/tmp").absolute()
room = Room.load("model/geometry/room.json")
config.PRESERVE_FOAM_LOG = True
```

(2) Build CFDManager and run CFD simulation
``` py linenums="1"
manager = CFDManager(room=room)
manager.run()
```

By running the code, the CFDManager will first establish the geometry according to the input 
geometry file ("room.json"). Subsequently, it will use the [Salome](https://www.salome-platform.org/) to
obtain the mesh files. Finally, it will use the solvers provided by [OpenFoam](https://www.openfoam.com/) to run the
*steady-state* simulation with the given boundary conditions. 

**Note**: we also provide the *transient* simulation option. However, the *transient* simulation is very time comsuming.
You can use the following code to run the *transient* simulation if you like it:
``` py linenums="1"
manager = CFDManager(room=room, steady=False)
manager.run()
```