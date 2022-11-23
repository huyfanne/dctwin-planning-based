The following diagram shows the architecture of the DCTwin engine. 

<figure markdown>
![image](../_static/images/DCTwin Architecture.png){ width="600"}
  <figcaption>Architecture of DCTwin</figcaption>
</figure>

The DCTwin engine consists of the backend, the digital twin layer, the co-sim manager and the 
interface layer.

*  The Backend layer corresponds to a specific simulation tool. Each simulator is hosted with a docker container. The
containers for the simulators can be found at the official repository of our
[DCWiz](https://github.com/orgs/cap-dcwiz/packages) platform

* The Digital Twin layer is a high-level abstraction of each simulator hosted at each backend. It provides the API for
running simulation with each backend simulator.

*  The co-sim manager is responsible for  the management of the co-simulation.

*  The interface layer provides various API for users to run simulations. The CFD Manager is used to run the standalone
CFD simulation. The POD Builder API is used to build the POD model. The Gym Interface provides the wrappers of the
OpenAI [Gym](https://github.com/openai/gym) environment. With the interface, the DCTwin engine can serve as a virtual
testbed so that the reinforcement learning agents in our [AI Engine](https://github.com/cap-dcwiz/dcwiz-ai-engine) can interact with