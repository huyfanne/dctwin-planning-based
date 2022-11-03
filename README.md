# DCTwin

DCTwin is a easy-to-use tool for building Digital Twin models for data centers.
Currently, the tool supports the following models:
* Energy Model  ([EnergyPlus](https://energyplus.net/))
* CFD Model ([OpenFoam](https://openfoam.org/))
* Reduced-order CFD Model ([Reducio]()) for real-time temperature field prediction to accelerate co-simultion


## Installation
```bash
poetry install
```
If you don't have poetry installed, you can install it with:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```
If you need to build the package, simple run:
```bash
poetry build
```
There will be a wheel file in the `dist` folder.

[//]: # (## Command line tools)

[//]: # (You can run the engine in a folder which has a file `room.yml`.)

[//]: # (The engine will create a folder `case` in your current folder.)

[//]: # ()
[//]: # (Create 3D geometry objects.)

[//]: # (```)

[//]: # (dce geometry)

[//]: # (```)

[//]: # ()
[//]: # (Create mesh.)

[//]: # (```)

[//]: # (dce mesh)

[//]: # (```)

[//]: # ()
[//]: # (Run solver.)

[//]: # (```)

[//]: # (dce solve)

[//]: # (```)

[//]: # ()
[//]: # (If you want to reuse the mesh files to solve, you can let the engine output to another folder.)

[//]: # (```)

[//]: # (dce solve --config thermal_test_1 --output case_thermal_test_1)

[//]: # (```)


## Usage
DCTwin provides Python interface for building models and running simulations. For more examples on how to use DCTwin
to build simulation models and run simulations,
please refer to the examples in the *tutorials* folder.