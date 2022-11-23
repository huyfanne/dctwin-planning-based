# Welcome to DCTWin Engine!

The DCTwin engine is a fully integrated component of the DCWiz platform. 
The <em> [digital twin](https://en.wikipedia.org/wiki/Digital_twin) </em> engine is one of the technological cores of the DCWiz
and it serves as a virtual testbed with which the learning-based controller interacts.
To be specific, we will design a simulation engine to collect the different simulators
from different disciplines together to perform a sophisticated multi-physics simulation.
With this high-fidelity interconnected digital twin platform, we can provide fine-grained
simulation functionality for each individual component of a data center.
For example, with the coupled data hall twin and the HVAC twin, we can investigate
how the temperature field within a data hall evolves with specific setpoints provided by
the HVAC system as well as the system energy consumption under the control policy.
By doing so, the learning agent can derive optimal policy by interacting with the coupled
digital twins while guaranteeing no local hot spots will occur.

## Key Components

* **Computational Fluid Dynamics (CFD) for Thermal Dynamics Simulation**: The DCTwin integrates the [OpenFOAM](https://www.openfoam.com/) for data hall thermodynamics modeling. It can simulate the fine-grained temperature/pressure/velocity field
* **Data Center Energy Modeling**: The DCTwin utilizes the [EnergyPlus](https://energyplus.net/) to simulate the energy consumption of each system component given the current system operation states (CRAC setpoints, flowrates, chilled water supply temperature etc). It can be used in the standalone mode to conduct the chiller plant energy simulation. Furthermore, it can also be coupled with the CFD engine to conduct system-wide simulation (thermodynamics of the data hall + energy dynamics of the chiller plant.)
* **Reduced Order Model / Surrogate Model for CFD**: The DCTwin engine also implements the Proper Orthogonal Decomposition (POD) based surrogate model, [Reducio](https://www.openfoam.com/),  for accelerating the CFD simulation. With the POD techniques, we can achieve *real-time* simulation of the data hall temperature distribution. This function is especially important if we want to run coupled CFD-Energy simulation since the CFD simulation is very time consuming (can be hours for a data hall of 300 square feets)


## Get Started
Get started with [Quick Start Guide](get_started/index.md).
