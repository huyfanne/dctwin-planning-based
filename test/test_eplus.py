import numpy as np
from dctwin.registraion import make_env

engine_config = "configs/test_eplus.prototxt"

env = make_env(
    env_proto_config=engine_config,
    reward_fn=lambda x: 0.0,
)

env.reset()

acu_setpoint_sp = 18.0
acu_supply_flow = 15.0
water_supply_sp = 7.0
act = np.array([acu_setpoint_sp, acu_supply_flow, water_supply_sp])

done = False

while not done:
    obs, rew, done, truncated, info = env.step(act)
