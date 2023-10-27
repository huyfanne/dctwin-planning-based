from dctwin.registraion import make_env
from pathlib import Path
from dctwin.utils import config as env_config
import os

engine_config = os.environ["CONFIG_PROTOTXT_PATH"]
log_dir = os.environ["LOG_DIR"]

env_config.LOG_DIR = Path(log_dir)
env_config.LOG_DIR.mkdir(parents=True, exist_ok=True)
env = make_env(
    env_proto_config=engine_config,
    reward_fn=lambda x: 0.0,
    is_k8s=True,
)
env.reset()
done = False
while not done:
    obs, rew, done, truncated, info = env.step([])
