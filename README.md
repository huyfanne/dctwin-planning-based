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

## Running Simulations in a Local Kubernetes Cluster

To run simulations in a local Kubernetes cluster, you can use k3d, which is a lightweight wrapper to run Rancher k3s in Docker. Here are the steps to set up and run simulations:

1. Install k3d. You can find the installation instructions on the [k3d GitHub page](https://github.com/rancher/k3d).

2. Create a k3d cluster and mount a local directory to it:

    ```bash
    k3d cluster create mycluster --volume /Users/ryan/Repo/dcwiz/dctwin/test/:/tm-data/
    ```

    Replace `/Users/ryan/Repo/dcwiz/dctwin/test/` with the path to your local directory.

3. Apply your Kubernetes secret configuration:

    ```bash
    kubectl apply -f test/secret.yaml
    ```

    Make sure to replace `test/secret.yaml` with the path to your secret configuration file.

4. Run the simulation:

    ```bash
    WORKER_NAME="test" K8S_NAMESPACE="default" CFD_RESOURCES="{\"cpu\": \"2000m\", \"memory\": \"4Gi\", \"ephemeral-storage\": \"1000Mi\"}" poetry run python test/test_cfd_k8s.py
    ```

    This command runs the simulation in the Kubernetes cluster. You can adjust the `WORKER_NAME`, `K8S_NAMESPACE`, and `CFD_RESOURCES` environment variables as needed.

Please refer to the *tutorials* folder for more examples on how to use DCTwin to build simulation models and run simulations.
