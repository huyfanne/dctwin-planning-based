from dctwin.registraion import make_env
from pathlib import Path
import os

engine_config = os.environ["CONFIG_PROTOTXT_PATH"]
env = make_env(
    env_proto_config=engine_config,
    reward_fn=lambda x: 0.0,
)
env.reset()
done = False
while not done:
    obs, rew, done, truncated, info = env.step([])
