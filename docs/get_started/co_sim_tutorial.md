In this tutorial, we will show how to conduct co-simulation for an air-cooled data center with one CRAC unit and a
chiller plant. In this case, the control variables are the the CRAC supply air flow rate and the supply air temperature
setpoint.

(1) Setup environment variables
```py linenums="1"
engine_config = "config.prototxt"
env_config.eplus.engine_config_file = engine_config
```

(2) Read configuration files
```py linenums="1"
config = read_engine_config(engine_config=engine_config)
setup_logging(config.logging_config, engine_config=engine_config)
```

(3) Build environment
```py linenums="1"
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
```

(4) Run EnergyPlus-CFD/POD co-simulation
```py linenums="1"
air_supply_sp = 20.0
air_supply_flowrate = 15.0
env.reset()
done = False
while not done:
    act = np.array([air_supply_sp, air_supply_flowrate])
    obs, rew, done, truncated, info = env.step(act)
```