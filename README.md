# DCTwin

Building CFD model for datacenters.


## Installation

```bash
pip install dctwin-1.0.1-py3-none-any.whl
```

## Command line tools
You can run the engine in a folder which has a file `room.yml`.
The engine will create a folder `case` in your current folder.

Create 3D geometry objects.
```
dce geometry
```

Create mesh.
```
dce mesh
```

Run solver.
```
dce solve
```

If you want to reuse the mesh files to solve, you can let the engine output to another folder.
```
dce solve --config thermal_test_1 --output case_thermal_test_1
```


## Python interface
Solving example:

```python
from dctwin.backend.foam import solver
from dctwin.models import Room

if __name__ == '__main__':
    room = Room.load('room.yml')
    solver.run(room, output='case_1', end_time=50)

    # Run with config file
    room.load_config('case_2_config.yml')
    solver.run(room, output='case_2')
```

Run a whole case:

```python
from dctwin.backend.foam import solver, snappyhex
from dctwin.backend.geometry import salome
from dctwin.models import Room

if __name__ == '__main__':
    room = Room.load('room.yml')
    # Building geometry
    salome.run(room)
    # Building mesh
    snappyhex.run(room)
    # Run solver
    solver.run(room)
```
