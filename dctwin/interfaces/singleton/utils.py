import json

from typing import Tuple
from loguru import logger

from dctwin.utils import config

from dctwin.models.basics import Vertex
from dctwin.models.constructions import Room

from pathlib import Path
from typing import Union, Dict

import numpy as np
import fluidfoam


def read_boundary_conditions(
    room: Room,
) -> np.ndarray:
    subfolders = [f for f in Path(config.CASE_DIR).iterdir() if f.is_dir()]
    num_cracs = len(room.objects.acus)
    boundary_conditions = np.zeros((len(subfolders), 2 * num_cracs + 2))
    for idx, subfolder in enumerate(subfolders):
        with open(Path(subfolder).joinpath("boundary condition.json"), "r") as f:
            boundary_condition_dict = json.load(f)
        boundary_conditions[idx, 0] = np.sum(list(boundary_condition_dict["server_powers"].values()))
        boundary_conditions[idx, 1] = np.sum(list(boundary_condition_dict["server_flow_rates"].values()))
        boundary_conditions[idx, 2:num_cracs+2] = np.array(list(boundary_condition_dict["crac_setpoints"].values()))
        boundary_conditions[idx, num_cracs+2:] = np.array(list(boundary_condition_dict["crac_flow_rates"].values()))
    return boundary_conditions


def read_object_mesh_index() -> Union[Dict, None]:
    try:
        with open(config.cfd.object_mesh_index, "r") as f:
            object_mesh_index = json.load(f)
    except FileNotFoundError:
        return None
    return object_mesh_index


def read_mesh_coordinates():
    assert Path(config.cfd.mesh_dir).exists(), \
        "mesh files not found"
    x, y, z = fluidfoam.readof.readmesh(
        str(config.cfd.mesh_dir), verbose=False
    )
    x = np.reshape(x, newshape=(-1, 1))
    y = np.reshape(y, newshape=(-1, 1))
    z = np.reshape(z, newshape=(-1, 1))
    return np.concatenate([x, y, z], axis=1)


def read_temperature(solution_dir: Path, end_time: str = "500"):
    logger.info(
        f"Reading temperature from "
        f"{solution_dir.joinpath(end_time, 'T')}"
    )
    temperature = fluidfoam.readof.readscalar(
        solution_dir, end_time, "T", verbose=False
    )
    temperature -= 273.15
    return temperature


def read_temperature_fields(end_time: str = "500") -> np.ndarray:
    experiment_dir_names = []
    subfolders = [f for f in config.CASE_DIR.iterdir() if f.is_dir()]
    for subfloder in subfolders:
        experiment_dir_names.append(subfloder)
    temperatures = []
    for experiment_dir_name in sorted(experiment_dir_names):
        try:
            temperature = read_temperature(experiment_dir_name, end_time=end_time)
            temperatures.append(temperature)
        except Exception:
            raise FileNotFoundError(
                f"fail to read temperature for "
                f"{experiment_dir_name.name}"
            )
    return np.asarray(temperatures)


def calc_object_mesh_index(room: Room, mesh_points: np.ndarray) -> Dict:

    def find_nearest_mesh_index(
        object_coodrinate: Vertex,
        mesh_coordinates: np.ndarray
    ):
        coordinates_array = np.asarray(
            [[object_coodrinate.x, object_coodrinate.y, object_coodrinate.z]]
        )
        return np.argmin(
            np.sum((coordinates_array - mesh_coordinates) ** 2, axis=1)
        )

    object_mesh_index = {"servers": {}, "cracs": {}, "sensors": {}}
    for ser_idx, ser in enumerate(room.objects.servers.values()):
        inlet_center, outlet_center = room.server_patch_positions(ser.id)
        nearest_inlet_mesh_index = find_nearest_mesh_index(inlet_center, mesh_points)
        nearest_outlet_mesh_index = find_nearest_mesh_index(outlet_center, mesh_points)
        object_mesh_index["servers"].update(
            {
                f"{ser.id}":
                    {
                        "inlet": int(nearest_inlet_mesh_index),
                        "outlet": int(nearest_outlet_mesh_index)
                    }
            }
        )

    for acu_idx, acu in enumerate(room.objects.acus.values()):
        return_center, supply_center = room.acu_patch_positions(acu.id)
        nearest_supply_mesh_index = find_nearest_mesh_index(supply_center, mesh_points)
        nearest_return_mesh_index = find_nearest_mesh_index(return_center, mesh_points)
        object_mesh_index["cracs"].update(
            {
                f"{acu.id}":
                    {
                        "supply": int(nearest_supply_mesh_index),
                        "return": int(nearest_return_mesh_index)
                    }
            }
        )
    for sen_idx, sen_loc in enumerate(room.probes):
        nearest_sensor_mesh_index = find_nearest_mesh_index(sen_loc, mesh_points)
        object_mesh_index["sensors"].update(
            {f"{sen_loc.id}": int(nearest_sensor_mesh_index)})

    return object_mesh_index


def check_base_dir(case_idx: int,  episode_idx: int = None) -> Tuple[bool, bool]:
    if config.cfd.mesh_dir != Path(""):
        base_case_path = Path(config.cfd.mesh_dir)
        assert Path.is_dir(base_case_path), "mesh is not a directory"
        assert Path.exists(base_case_path), "mesh directory not exists"
        run_geometry, run_mesh, mesh_path = False, False, base_case_path
        if episode_idx is None:
            config.CASE_DIR = Path(config.LOG_DIR).joinpath(
                f"simulation-{case_idx}"
            )
        else:
            config.CASE_DIR = Path(config.LOG_DIR).joinpath(
                "cfd_output", f"episode-{episode_idx}", f"simulation-{case_idx}"
            )
    else:
        run_geometry, run_mesh = True, True
        config.CASE_DIR = Path(config.LOG_DIR).joinpath("base")
        config.cfd.mesh_dir = config.CASE_DIR
    return run_geometry, run_mesh


def save_json_file(path: Union[Path, str], saved_dict: Dict) -> None:
    with open(path, "w") as f:
        json.dump(saved_dict, f, indent=4)
