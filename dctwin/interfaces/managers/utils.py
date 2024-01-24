import json
import time

from typing import Tuple

import torch
from loguru import logger

from dctwin.utils import config

from dctwin.models import Vertex
from dctwin.models import Room

from pathlib import Path
from typing import Union, Dict, Optional

import numpy as np
import fluidfoam


def read_boundary_conditions(
    room: Room,
) -> np.ndarray:
    subfolders = [
        f
        for f in Path(config.cfd.case_dir).iterdir()
        if f.is_dir() and f.name != "base"
    ]
    num_acus = len(room.constructions.acus)
    boundary_conditions = np.zeros((len(subfolders), 2 * num_acus + 2))
    for idx, subfolder in enumerate(
        sorted(subfolders, key=lambda x: int(x.name.split("-")[-1]))
    ):
        with open(Path(subfolder).joinpath("boundary_conditions.json"), "r") as f:
            boundary_condition_dict = json.load(f)
        boundary_conditions[idx, 0] = np.sum(
            list(boundary_condition_dict["server_powers"].values())
        )
        boundary_conditions[idx, 1] = np.sum(
            list(boundary_condition_dict["server_volume_flow_rates"].values())
        )
        supply_air_temperatures = []
        supply_air_volume_flow_rates = []
        for acu_name, acu in room.constructions.acus.items():
            supply_air_temperatures.append(
                boundary_condition_dict["supply_air_temperatures"][acu_name]
            )
            supply_air_volume_flow_rates.append(
                boundary_condition_dict["supply_air_volume_flow_rates"][acu_name]
            )
        boundary_conditions[idx, 2 : num_acus + 2] = np.array(supply_air_temperatures)
        boundary_conditions[idx, num_acus + 2 :] = np.array(
            supply_air_volume_flow_rates
        )
    return boundary_conditions


def read_object_mesh_index(room: Room = None) -> Union[Dict, None]:
    try:
        with open(config.cfd.object_mesh_index, "r") as f:
            object_mesh_index = json.load(f)
    except FileNotFoundError:
        if room is not None and Path(config.cfd.mesh_dir) != Path(""):
            object_mesh_index = calc_object_mesh_index(
                room=room,
                mesh_points=read_mesh_coordinates(),
            )
        else:
            return None
    return object_mesh_index


def read_mesh_coordinates() -> np.ndarray:
    assert Path(config.cfd.mesh_dir).exists(), "mesh files not found"
    logger.info(f"Reading mesh coordinates from {config.cfd.mesh_dir}")
    x, y, z = fluidfoam.readof.readmesh(str(config.cfd.mesh_dir), verbose=False)
    x = np.reshape(x, newshape=(-1, 1))
    y = np.reshape(y, newshape=(-1, 1))
    z = np.reshape(z, newshape=(-1, 1))
    return np.concatenate([x, y, z], axis=1)


def read_temperature(solution_dir: Path, end_time: str = "500"):
    logger.info(f"Reading temperature from " f"{solution_dir.joinpath(end_time, 'T')}")
    temperature = fluidfoam.readof.readscalar(
        solution_dir, end_time, "T", verbose=False
    )
    temperature -= 273.15
    return temperature


def read_temperature_fields(end_time: str = "500") -> np.ndarray:
    subfolders = [
        f for f in config.cfd.case_dir.iterdir() if f.is_dir() and f.name != "base"
    ]
    temperatures = []
    for subfloder in sorted(subfolders, key=lambda x: int(x.name.split("-")[-1])):
        try:
            temperature = read_temperature(subfloder, end_time=end_time)
            temperatures.append(temperature)
        except Exception:
            raise FileNotFoundError(
                f"fail to read temperature for " f"{subfloder.name}"
            )
    return np.asarray(temperatures)


def read_sensor_temperature_results(
    room: Optional[Room] = None,
    case: Optional[Union[str, Path]] = None,
    object_mesh_index: Optional[Dict] = None,
    temperature: Optional[Union[np.ndarray, torch.Tensor]] = None,
):
    results = {}
    if object_mesh_index is not None:
        # read from object_mesh_index
        assert temperature is not None, "temperature field is not provided"
        temperature = (
            temperature.detach().cpu().numpy()
            if isinstance(results, torch.Tensor)
            else temperature
        )
        for sensor_id, index in object_mesh_index["sensors"].items():
            results[sensor_id] = round(float(temperature.squeeze()[index]), 2)
    else:
        # read from postProcessing folder
        assert room is not None, "room is not provided"
        post_process_time = time.time()
        while True:
            if Path(f"{case}/postProcessing/probes/0/T").exists():
                break
            else:
                if time.time() - post_process_time > 100:
                    logger.critical(f"{case}/postProcessing/probes/0/T not found")
                    exit(-1)
                continue
        with open(f"{case}/postProcessing/probes/0/T") as f:
            for i in f:
                if i.startswith("#"):
                    continue
                else:
                    for idx, key in enumerate(room.constructions.sensors.keys()):
                        results[key] = round(float(i.split()[idx + 1]) - 273.15, 2)

    return results


def calc_object_mesh_index(room: Room, mesh_points: np.ndarray) -> Dict:
    def find_nearest_mesh_index(
        object_coodrinate: Vertex,
        mesh_coordinates: np.ndarray,
    ) -> int:
        coordinates_array = np.asarray(
            [[object_coodrinate.x, object_coodrinate.y, object_coodrinate.z]]
        )
        return int(
            np.argmin(np.sum((coordinates_array - mesh_coordinates) ** 2, axis=1))
        )

    object_mesh_index = {"servers": {}, "acus": {}, "sensors": {}}

    for rack in room.constructions.racks.values():
        for ser_idx, ser in rack.constructions.servers.items():
            inlet_center, outlet_center, _ = room.constructions.server_patch_positions(
                ser_idx
            )
            nearest_inlet_mesh_index = find_nearest_mesh_index(
                inlet_center, mesh_points
            )
            nearest_outlet_mesh_index = find_nearest_mesh_index(
                outlet_center, mesh_points
            )
            object_mesh_index["servers"].update(
                {
                    f"{ser_idx}": {
                        "inlet": int(nearest_inlet_mesh_index),
                        "outlet": int(nearest_outlet_mesh_index),
                    }
                }
            )

    for acu_idx, acu in room.constructions.acus.items():
        return_center, supply_center, _ = room.constructions.acu_patch_positions(
            acu_idx
        )
        nearest_supply_mesh_index = find_nearest_mesh_index(supply_center, mesh_points)
        nearest_return_mesh_index = find_nearest_mesh_index(return_center, mesh_points)
        object_mesh_index["acus"].update(
            {
                f"{acu_idx}": {
                    "supply": int(nearest_supply_mesh_index),
                    "return": int(nearest_return_mesh_index),
                }
            }
        )
    for sen_idx, sen in room.constructions.sensors.items():
        nearest_sensor_mesh_index = find_nearest_mesh_index(
            sen.geometry.location, mesh_points
        )
        object_mesh_index["sensors"].update(
            {f"{sen_idx}": int(nearest_sensor_mesh_index)}
        )

    return object_mesh_index


def check_base_dir(case_idx: int, episode_idx: int = None) -> Tuple[bool, bool]:
    if config.cfd.mesh_dir != Path(""):
        base_case_path = Path(config.cfd.mesh_dir)
        assert Path.is_dir(base_case_path), "mesh is not a directory"
        assert Path.exists(base_case_path), "mesh directory not exists"
        run_geometry, run_mesh, mesh_path = False, False, base_case_path
        if episode_idx is None:
            config.cfd.case_dir = Path(config.LOG_DIR).joinpath(
                f"simulation-{case_idx}"
            )
        else:
            config.cfd.case_dir = Path(config.LOG_DIR).joinpath(
                "cfd_output", f"episode-{episode_idx}", f"simulation-{case_idx}"
            )
        if config.cfd.dry_run:
            config.cfd.case_dir = Path(config.LOG_DIR).joinpath("base")
    else:
        if Path.is_dir(Path(config.LOG_DIR).joinpath("base/constant/polyMesh")):
            run_geometry, run_mesh = False, False
        else:
            run_geometry, run_mesh = True, True
        config.cfd.case_dir = Path(config.LOG_DIR).joinpath("base")
        config.cfd.mesh_dir = config.cfd.case_dir

    return run_geometry, run_mesh


def save_json_file(path: Union[Path, str], saved_dict: Dict) -> None:
    with open(path, "w") as f:
        json.dump(saved_dict, f, indent=4)
