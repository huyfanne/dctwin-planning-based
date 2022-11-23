## Code Structure
- `backends/` is the core engine package
    - `eplus/` provide the wrapper for running EnergyPlus simulation
      - `core.py` provide entry API for running one-step simulation
      - `eplus_logger.py` formatter for EnergyPlus outputs and run-time logging info
      - `parser.py` parser for generating a run-time IDF file with user input configuration file and a template IDF file
    - `foam/`
      - `boundary.py`
      - `parser.py`
      - `snappyhex.py`
      - `solver.py`
      - `utils.py`
    - `geometry/` 
      - `README.md`
      - `salome.py`
    - `rom/` 
        - `pod/`
            - `core.py` provide entry point to run one-step POD simulation
            - `model.py` define the multi-output GP model for POD coefficient prediction
    - `core.py` the abstract core implementation for the backend 
- `interfaces/` provide the interface for outside users.
  - `gym_env/`
    - `base_env.py` abstract class for the Gym environment
    - `eplus_env.py` Gym environment for standalone EnergyPlus simulation
    - `cosim_env.py` Gym environment for EnergyPlus-CFD(POD) co-simulation
  - `manager/`
    - `cfd_manager.py` provide the API for running standalone CFD simulation
    - `pod_builder.py` provide the API for building POD-GP model
    - `utiles.py` provide utility functions for the managers

- `models/` provide the model objects for building CFD simulation models
    - `basic.py`
    - `constructions.py`
    - `geometry.py`
    - `objects.py`
    - `servers.py`

- `templates/` provide template fils for the backend simulators

- `utils/` provide the utility functions for the engine
  - `config.py` define environment variable configuration class
  - `dt_engine_pb2.py` define the protobuf message for the engine
  - `error.py` provide base class for handling run-time errors for different backends
  - `template.py`: load template files for the backend simulators into the environment variables

- `registration.` provide Gym Environment interface to outside users