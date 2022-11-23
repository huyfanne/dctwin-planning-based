In this tutorial, we will show how to conduct energy simulation for an air-cooled data center
with 5 data halls and a chiller plant with 5 chillers. In this case, the control variables is
the **chilled water supply temperature**.

(1) Setup environment variables
``` py linenums="1"
engine_config = "config.prototxt"
env_config.eplus.engine_config_file = engine_config
```

(2) Read configuration files
```py linenums="1"
config = read_engine_config(engine_config=engine_config)
setup_logging(config.logging_config, engine_config=engine_config)
```

(3) Build the environment
``` py linenums="1"
env_config_name = config.WhichOneof("EnvConfig")
env_params = json_format.MessageToDict(
    getattr(config, env_config_name).env_params,
    preserving_proto_field_name=True,
)
env = EPlusEnv(
    config=getattr(config, env_config_name),
    reward_fn=None,
    schedule_fn=None,
    **env_params,
)
```

(4) Run the simulation
``` py linenums="1"
water_supply_sp = 12.0
env.reset()
done = False
while not done:
    act = np.array([water_supply_sp])
    obs, rew, done, truncated, info = env.step(act)
```