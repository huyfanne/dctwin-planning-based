from dctwin.utils import config
from dctwin.models import Room
from dctwin.interfaces import CFDManager

import os
import json
import shutil
import docker
from pathlib import Path

docker_client = docker.DockerClient(base_url="unix://var/run/docker.sock")


def kelvin_to_celsius(kelvin, round_to=None):
    if round_to:
        return round(float(kelvin) - 273.15, round_to)
    else:
        return float(kelvin) - 273.15


def get_field_config(min_level, max_level, server_level=2):
    return {
        "acu_wall": {
            "type": "wall",
            "level": max_level,
            "refine_level": f"({min_level} {max_level})",
        },
        "acu_return": {
            "type": "patch",
            "level": max_level,
            "refine_level": f"({min_level} {max_level})",
        },
        "acu_supply": {
            "type": "patch",
            "level": max_level,
            "refine_level": f"({min_level} {max_level})",
        },
        "server_inlet": {
            "type": "patch",
            "level": server_level,
            "refine_level": f"({server_level} {server_level})",
        },
        "server_outlet": {
            "type": "patch",
            "level": server_level,
            "refine_level": f"({server_level} {server_level})",
        },
        "server_wall": {
            "type": "wall",
            "level": server_level,
            "refine_level": f"({server_level} {server_level})",
        },
        "rack_wall": {
            "type": "wall",
            "level": max_level,
            "refine_level": f"({min_level} {max_level})",
            "faceType": "baffle",
        },
    }


def parse_and_upload_result(room, case_dir, host_data_path):
    base_files = host_data_path / "cosim/base-files"
    shutil.copy(base_files / "result.py", case_dir)
    servers = []
    acus = []
    for rack in room.constructions.racks.values():
        for key, server in rack.constructions.servers.items():
            inlet_center, outlet_center = room.server_patch_positions(key)
            result = [inlet_center.__dict__, outlet_center.__dict__, key]
            servers.append(result)
    for key, acu in room.constructions.acus.items():
        return_center, supply_center = room.acu_patch_positions(key)
        result = [return_center.__dict__, supply_center.__dict__]
        acus.append(result)

    with open(case_dir / "probes.json", "w") as f:
        json.dump(
            {
                "servers": servers,
                "acus": acus,
            },
            f,
        )
    docker_client.containers.run(
        "ntucap/paraview",
        command="pvpython /data/result.py",
        auto_remove=True,
        environment={
            "WIDTH": max(i.x for i in room.geometry.plane)
                     - min(i.x for i in room.geometry.plane),
            "DEPTH": max(i.y for i in room.geometry.plane)
                     - min(i.y for i in room.geometry.plane),
            "HEIGHT": room.geometry.height,
        },
        volumes=[f"{case_dir}:/data"],
        working_dir="/data",
        detach=False,
    )


def calculate_metrics(case_dir, room, threshold):
    file_path = case_dir / "results.json"
    if not file_path.exists():
        return None

    with open(file_path) as f:
        results_data = json.load(f)
        server_tmp = 0
        server_tmp_count = 0
        hotspot_list = []

        for i, item in enumerate(results_data["servers"]):
            if item[0] != 0 and item[1] != 0:
                server_tmp += item[1] - item[0]
                server_tmp_count += 1
                if item[0] > threshold + 273.15:
                    server_data = results_data["servers_data"][i]
                    hotspot_list.append(
                        {
                            "id": server_data["id"],
                            "inlet_location": server_data["inlet_location"],
                            "inlet_temperature": kelvin_to_celsius(item[0]),
                        }
                    )

        acus_tmp = 0
        acus_tmp_count = 0
        for item in results_data["acus"]:
            if item[0] != 0 and item[1] != 0:
                acus_tmp += item[0] - item[1]
                acus_tmp_count += 1

        results = []
        sensor_results = []
        if os.path.exists(case_dir / "postProcessing"):
            with open(case_dir / "postProcessing/probes/0/T") as temperature_result:
                for line in temperature_result:
                    if not line.startswith("#"):
                        results.append(
                            lambda x: kelvin_to_celsius(x, 2) for x in line.split()[1:]
                        )
                        results.append(
                            list(map(lambda x: kelvin_to_celsius(x, 2), line.split()[1:]))
                        )
            probe_results = results[-1]
            assert len(room.probes) == len(probe_results)
            for i, sensor in enumerate(room.probes):
                data = sensor.dict()
                data["result"] = probe_results[i]
                sensor_results.append(data)

        avg_acus_tmp = acus_tmp / acus_tmp_count
        avg_server_tmp = server_tmp / server_tmp_count

        return {
            "rti": round(avg_acus_tmp / avg_server_tmp, 2) * 100,
            "tmp": round(avg_acus_tmp, 2),
            "hotspots": len(hotspot_list),
            "hotspot_list": hotspot_list,
            "it_load": sum(
                server.heat_load for server in room.inputs.servers.values()
            ),
            "sensor_list": sensor_results,
        }


host_workspace = Path(os.environ["HOST_WORKSPACE"])
host_data_path = Path(os.environ["HOST_DATA_PATH"])
host_case_dir = host_workspace / "run/result"
config.CASE_DIR = host_case_dir
config.PRESERVE_FOAM_LOG = True
config.LOG_DIR = host_workspace / "run/result"
config.cfd.mesh_dir = ""

room = Room.load(host_workspace / "model/model.dt")
cfd_manager = CFDManager(room=room, mesh_process=32, solve_process=32, end_time=100)
cfd_manager.run()

case_dir = host_workspace / "run/result/base"
parse_and_upload_result(room, case_dir, host_data_path)
with open(host_workspace / "config/preferences.json", "r") as f:
    data = json.load(f)
metrics_data = calculate_metrics(
                case_dir=case_dir,
                room=room,
                threshold=data["threshold"],
            )

os.mkdir(host_workspace / "run/cache_result")
if metrics_data:
    with open(host_workspace / "run/cache_result/metric.json", "w") as file:
        file.write(json.dumps(metrics_data))
shutil.copytree(case_dir / "airflow", host_workspace / "run/cache_result/airflow")
shutil.copytree(case_dir / "thermal", host_workspace / "run/cache_result/thermal")

shutil.make_archive(host_workspace / "run/cache_result", "zip", host_workspace / "run/cache_result")
shutil.make_archive(host_workspace / "run/result", "zip", host_workspace / "run/result")

shutil.rmtree(host_workspace / "run/cache_result")
shutil.rmtree(host_workspace / "run/result")

