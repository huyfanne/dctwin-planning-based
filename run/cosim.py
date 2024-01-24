import numpy as np

from dctwin.interfaces.gym_envs import CoSimEnv
from dctwin.utils import config as env_config
from dctwin.utils import read_engine_config, setup_logging
from dctwin.adapters import EplusCFDAdapter
from typing import Dict
from google.protobuf import json_format
import os
from pathlib import Path
import shutil
import json


def map_boundary_condition_fn(
    eplus_adaptor: EplusCFDAdapter,
    action_dict: Dict,
) -> Dict:
    """
    Map the action dict into boundary condition dict with a given format.
    Boundary conditions should include supply temperature, supply
    volumetric flow rate, server powers and server flow rates.
    Server power and server flow rate are computed in a model-based manner
    with the model from Eplus. The curve parameters for the server power model
    and flow rate model are from parsing the idf file automatically.
    """
    boundary_conditions = {
        "supply_air_temperatures": {},
        "supply_air_volume_flow_rates": {},
        "server_powers": {},
        "server_volume_flow_rates": {},
    }
    for crac in eplus_adaptor.eplus_manager.idf_parser.epm.AirLoopHVAC:
        uid = eplus_adaptor.idf2room_mapper[crac.name]
        boundary_conditions["supply_air_temperatures"][uid] = action_dict[
            f"{uid}_setpoint"
        ]
        boundary_conditions["supply_air_volume_flow_rates"][uid] = (
            action_dict[f"{uid}_flow_rate"] / eplus_adaptor.rho_air
        )
    for idx, it_equipment in enumerate(
        eplus_adaptor.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled
    ):
        for server_id in eplus_adaptor.idf2room_mapper[it_equipment.name]["servers"]:
            heat_load = eplus_adaptor.eplus_manager.idf_parser.compute_server_power(
                utilization=action_dict[f"cpu_loading_schedule{idx + 1}"],
                inlet_temperature=eplus_adaptor.server_inlet_temps[server_id],
                name=it_equipment.name,
            )
            volume_flow_rate = (
                eplus_adaptor.eplus_manager.idf_parser.compute_server_flow_rate(
                    utilization=action_dict[f"cpu_loading_schedule{idx + 1}"],
                    inlet_temperature=eplus_adaptor.server_inlet_temps[server_id],
                    name=it_equipment.name,
                )
            )
            boundary_conditions["server_powers"][server_id] = heat_load
            boundary_conditions["server_volume_flow_rates"][
                server_id
            ] = volume_flow_rate

    return boundary_conditions


logging_dir = Path(os.environ["LOGGING_DIR"])
host_prototxt_path = Path(os.environ["HOST_PROTOTXT_PATH"])
set_points_path = Path(os.environ["SET_POINTS_PATH"])
engine_config = host_prototxt_path
env_config.eplus.engine_config_file = engine_config
config = read_engine_config(engine_config=engine_config)

env_config.LOG_DIR = logging_dir
env_config.LOG_DIR.mkdir(parents=True, exist_ok=True)
shutil.copy(engine_config, env_config.LOG_DIR.joinpath(f"{engine_config.name}"))


env_config_name = config.WhichOneof("EnvConfig")
env_params = json_format.MessageToDict(
    getattr(config, env_config_name).env_params,
    preserving_proto_field_name=True,
)
env = CoSimEnv(
    config=getattr(config, env_config_name),
    reward_fn=None,
    schedule_fn=None,
    map_boundary_condition_fn=map_boundary_condition_fn,
    **env_params,
)
env.reset()

with open(set_points_path, "r") as f:
    action_dict = json.load(f)

act = np.array(
    [
        action_dict["ACU1_setpoint"],
        action_dict["ACU1_flow_rate"],
        action_dict["chw_supply_sp"],
    ]
)
done = False
env_config.cfd.dry_run = True
env_config.cfd.mesh_dir = env_config.LOG_DIR.joinpath("base")
while not done:
    obs, rew, done, truncated, info = env.step(act)
