In this toturial, we will go through how to run multiple CFD simulations with different boundary conditions to form a CFD
simulation dataset and build the POD model to accelerate CFD simulation.

* **[Environment configuration](#build-cfd-simulation-dataset)**: running multiple CFD simulations with different boundary conditions to form a CFD simulation dataset 
* **[POD model building](#build-pod-based-reduced-order-model)**: building the POD model to accelerate CFD simulation

## Build CFD Simulation Dataset
The room model is identical to the one in tutorial/cfd, which is a
data hall containing one CRAC unit and 20 racks.

(1) Load the simulation plan
``` py linenums="1"
with open("simulation_plan.yaml", "r") as f:
    simulation_plan = yaml.safe_load(f)
```
The simulation plan is a yaml file that specifies the boundary conditions for each CFD simulation:
* server_flow_rate_noise: whether to add noise to the server flow rate
* noise_factor: standard deviation of the noise added to the server flow rate
* server_flow_rate_factor: the ratio between the total server flow rate and the total CRAC supply flow rate
* supply_temp: CRAC supply temperate used in the simulation
* supply_flow_rate: CRAC supply flow rate (kg/s) used in the simulation.
* cpu_load_scheduling: server CPU utilization used in the simulation.

In this case, we will build a CFD simulation dataset with #supply_temp $\times$ #supply_flow_rate $\times$ #cpu_load_scheduling samples.

(2) Configure logging directory
``` py linenums="1"
config = read_engine_config(engine_config="config.prototxt")
setup_logging(config.logging_config, engine_config="config.prototxt")
```

(3) Set the geometry/mesh dir. This is useful if you have obtained a directory that containing the geometry and mesh
files. In this case, no additional geometry/meshing running will be conducted to speed-up the simulation.
``` py linenums="1"
env_config.cfd.mesh_dir = config.hybrid_env_config.cfd.mesh_dir
```

(4) Load the room model, which serves as the input to the geometry/mesh module of the CFDBackend
``` py linenums="1"
room = Room.load(config.hybrid_env_config.cfd.geometry_file)
```

(5) Build the CFDManager. To see how the CFDManager works, please refer to the tutorial/cfd/example.ipynb for more details.
``` py linenums="1"
cfd_manager = CFDManager(
    room=room,
    write_interval=100,
    end_time=500,
)
```

(6) Setup EnergyPlus idf file parser. Since the POD is used to couple with the EnergyPlus to perform co-simulation,
we should use the power curve specified in the EnergyPlus model file to calculate the server power consumption.
``` py linenums="1"
idf_parser = IDFParser(config.hybrid_env_config.eplus.model_file)
```

(7) Setup EnergyPlus-CFD object mapping.
``` py linenums="1"
with open(config.hybrid_env_config.cfd.idf2room_map) as f:
    idf2room_mapper = json.load(f)
```
The object maps the object name in the idf files (e.g., "west zone air system") to the object names in the geometry file
(e.g., "ACU1"). In the EnergyPlus, each thermal zone should be equipped with a "ITEElectricalEquipment:AirCooled" object.
To build the co-simulation model, we should specify which physical servers belongs to this EnergyPlus object so that we
can set the power boundary condition for the serve belongs to it.

(8) Conducting the simulation plan. Multiple CFD simulation will be conducted with different boundary conditions and fixed geometry. Note: we do not consider the relationship between server power consumption and server inlet temperature and assume that the server power consumption is proportional to the CPU utilization, which is also a common setting in data center modeling. In the future, we will consider adding this feature to enhance the simulation model.
``` py linenums="1"
rho_air = 1.19
case_idx = 1
for supply_temp in simulation_plan["supply_temp"]:
    for supply_flow_rate in simulation_plan["supply_flow_rate"]:
        for utilization in simulation_plan["cpu_load_scheduling"]:
            # initialize boundary condition dictionary
            boundary_conditions = {
                "crac_setpoints": {}, "crac_flow_rates": {},
                "server_powers": {}, "server_flow_rates": {}
            }
            # set CRAC boundary conditions
            for crac in idf_parser.epm.AirLoopHVAC:
                uid = idf2room_mapper[crac.name]
                boundary_conditions["crac_setpoints"][uid] = supply_temp
                boundary_conditions["crac_flow_rates"][uid] = supply_flow_rate / rho_air
            # compute server power and server flow rate according to CPU load scheduling
            for it_equipment in idf_parser.epm.ElectricEquipment_ITE_AirCooled:
                for server_id in idf2room_mapper[it_equipment.name]["servers"]:
                    heat_load = idf_parser.compute_server_power(
                        utilization=utilization,
                        inlet_temperature=None,
                        name=it_equipment.name
                    )
                    mass_flow_rate = idf_parser.compute_server_flow_rate(
                        heat_load,
                        name=it_equipment.name,
                    )
                    if simulation_plan["server_flow_rate_noise"]:
                        mu = mass_flow_rate
                        sigma = simulation_plan["noise_factor"] * mass_flow_rate
                        mass_flow_rate = np.clip(np.random.normal(loc=mu, scale=sigma),
                                                 a_min=mu-3*sigma, a_max=mu+3*sigma)
                    volume_flow_rate = mass_flow_rate / rho_air
                    boundary_conditions["server_powers"][server_id] = heat_load
                    boundary_conditions["server_flow_rates"][server_id] = volume_flow_rate
            # scale server flow rate according to the supply air flow rate
            for it_equipment in idf_parser.epm.ElectricEquipment_ITE_AirCooled:
                uid = idf2room_mapper[it_equipment.name]["crac"]
                supply_flow_rate = boundary_conditions["crac_flow_rates"][uid]
                sum_server_flow_rate = 0
                for server_id in idf2room_mapper[it_equipment.name]["servers"]:
                    sum_server_flow_rate += boundary_conditions["server_flow_rates"][server_id]
                scale_factor = supply_flow_rate * simulation_plan["server_flow_rate_factor"] / sum_server_flow_rate
                for server_id in idf2room_mapper[it_equipment.name]["servers"]:
                    boundary_conditions["server_flow_rates"][server_id] *= scale_factor
            # inform boundary conditions
            total_power = sum(boundary_conditions["server_powers"].values())
            total_server_flow_rate = sum(boundary_conditions["server_flow_rates"].values())
            logger.info(f" # Simulation = {case_idx},"
                        f" SupplyT = {supply_temp},"
                        f" SupplyM = {round(supply_flow_rate, 2)},"
                        f" Q = {round(float(total_power), 2)},"
                        f" ServerM = {round(float(total_server_flow_rate), 2)}")
            # save boundary condition
            cfd_manager.run(
                remove_foam_log=False,
                case_index=case_idx,
                **boundary_conditions
            )
            case_idx += 1
```
Alternatively, you can also run co-simulation with to obtain the CFD simulation dataset. What distinguish co-sim with 
the above batch CFD simulation example: by running the co-simulation, we can get a temperature trajectory where we can
consider the server and fan power consumption related to the server inlet temperature. Specifically, at the of time
slot $t$, the server power is computed as $P_{t} = f(u_{t}, T^{in}_{t-1})$ and the server flow rate will be computed
as $m_{t} = g(u_{t}, T^{in}_{t-1})$. Where the $T^{in}_{t-1}$ is the server inlet temperature at the beggining of
the time slot $t$ which has already been computed by running the simulation at the time slot $t-1$. In the batch CFD
mode, we cannot know the server inlet temperature in advance and we cannot model the server power consumption as a
function of server inlet tempearture.
``` py linenums="1"
from google.protobuf import json_format
from dctwin.interfaces import CoSimEnv

# initialize environment
env_config_name = config.WhichOneof("EnvConfig")
env_params = json_format.MessageToDict(
    getattr(config, env_config_name).env_params,
    preserving_proto_field_name=True,
)
env = CoSimEnv(
    config=getattr(config, env_config_name),
    reward_fn=None,
    schedule_fn=None,
    **env_params,
)

# reset environment
env.reset()

# conduct simulation plan
for supply_temp in simulation_plan["supply_temp"]:
    for supply_flow_rate in simulation_plan["supply_flow_rate"]:
        for utilization in simulation_plan["cpu_load_scheduling"]:
            env.step(
                raw_action=np.asarray([utilization, supply_temp, supply_flow_rate])
            )

# close environment and clean up all running containment
env.close()
```

## Build POD-based Reduced Order Model
(1) Setup POD Builder.
``` py linenums="1"
env_config.cfd.mesh_dir = "log/base"
env_config.CASE_DIR = "{directory that stores CFD simulation results}"
room = Room.load("model/geometry/room.json")
builder = PODBuilder(
    room=room,
    num_modes=5,
    max_iter=100
)
```
(2) Run builder to obtain POD modes and GP models. The POD Builder will first read all temperature fields in the 
cfd_result_dir and then calculates the POD modes. Subsequently, it will build the GP models to predict the POD
coefficients for arbitrary boundary conditions.
``` py linenums="1"
builder.run()
```
(3) Save the POD modes and GP models.
``` py linenums="1" 
builder.save(
    save_path="{path to save the results}"
)
```