from dctwin.utils import config
from dctwin.models.cfd.room import Room
from dctwin.interfaces import CFDManager
from dctwin.backends.core_k8s import create_job_object, create_job, wait_for_job
from loguru import logger

import os
import json
import shutil
from pathlib import Path
from kubernetes import config as k8s_config, client
import uuid

field_config = {
    "server_inlet": {"type": "patch", "level": 3, "refine_level": "(0 3)"},
    "server_outlet": {"type": "patch", "level": 3, "refine_level": "(0 3)"},
    "server_wall": {"type": "wall", "level": 3, "refine_level": "(0 3)"},
    "rack_wall": {
        "type": "wall",
        "level": 3,
        "refine_level": "(0 3)",
        "faceType": "baffle",
    },
    "rack_panel": {
        "type": "wall",
        "level": 3,
        "refine_level": "(0 3)",
        "faceType": "baffle",
    },
}


def kelvin_to_celsius(kelvin, round_to=None):
    if round_to:
        return round(float(kelvin) - 273.15, round_to)
    else:
        return float(kelvin) - 273.15


def highest_2_power_less_than_cpu_count():
    cpu_count = os.cpu_count()
    power = 0
    while cpu_count > 1:
        power += 1
        cpu_count = cpu_count >> 1
    return 2**power


def parse_and_upload_result(room: Room, case_dir, host_base_files_path, iteration):
    shutil.copy(host_base_files_path / "result.py", case_dir)
    servers = []
    acus = []
    for server_id in room.constructions.server_keys:
        inlet_center, outlet_center, _ = room.constructions.server_patch_positions(
            server_id
        )
        result = [inlet_center.__dict__, outlet_center.__dict__, server_id]
        servers.append(result)
    for acu_id in room.constructions.acu_keys:
        return_center, supply_center, _ = room.constructions.acu_patch_positions(acu_id)
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

    command = ["pvpython", "/data/result.py"]
    working_dir = "/data"
    namespace = "dcwiz"
    worker_name = os.environ["WORKER_NAME"]
    job_name = uuid.uuid4()
    image = "ntucap/paraview"
    k8s_config.load_incluster_config()
    # Note: we need to use both the core_v1 and batch_v1 APIs. The previous one is for the pods, the latter for the jobs
    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()

    job_name = f"{worker_name}-{job_name}"
    pvc_name = f"task-manager-worker-data-{worker_name}"
    backoff_limit = 0
    environment = {
        "WIDTH": str(
            max(i.x for i in room.geometry.plane)
            - min(i.x for i in room.geometry.plane)
        ),
        "DEPTH": str(
            max(i.y for i in room.geometry.plane)
            - min(i.y for i in room.geometry.plane)
        ),
        "HEIGHT": str(room.geometry.height),
    }

    job = create_job_object(
        client,
        batch_v1,
        namespace=namespace,
        job_name=job_name,
        pvc_name=pvc_name,
        image=image,
        command=command,
        backoff_limit=backoff_limit,
        ttl_seconds_after_finished=10,
        env_vars=environment,
        working_dir=working_dir,
        case_dir=case_dir,
        volume_data_dir="/data",
    )

    create_job(batch_v1, job)

    stream_log = wait_for_job(
        batch_v1, core_v1, job_name, namespace=namespace, backoff_limit=backoff_limit
    )
    for line in stream_log:
        logger.info(line.decode("utf-8").splitlines())


def calculate_metrics(case_dir, room: Room, threshold):
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
                            list(
                                map(lambda x: kelvin_to_celsius(x, 2), line.split()[1:])
                            )
                        )
            probe_results = results[-1]
            assert room.constructions.num_sen == len(probe_results)
            for i, sensor in enumerate(room.constructions.sensors.values()):
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
                server.input_power for server in room.inputs.servers.values()
            ),
            "sensor_list": sensor_results,
        }


host_workspace = Path(os.environ["HOST_WORKSPACE"])
host_base_files_path = Path(os.environ["HOST_BASE_FILES_PATH"])
host_case_dir = host_workspace / "run/result"
config.CASE_DIR = host_case_dir
config.PRESERVE_FOAM_LOG = True
config.LOG_DIR = host_workspace / "run/result"
config.cfd.mesh_dir = ""

with open(host_workspace / "config/preferences.json", "r") as f:
    preference = json.load(f)
room = Room.load(host_workspace / "model/model.dt")
max_processes = highest_2_power_less_than_cpu_count()
cfd_manager = CFDManager(
    room=room,
    mesh_process=min(16, max_processes),
    solve_process=min(16, max_processes),
    end_time=int(preference["iteration"]),
    field_config=field_config,
    is_k8s=True,
)

cfd_manager.run()

case_dir = host_workspace / "run/result/base"
parse_and_upload_result(room, case_dir, host_base_files_path, preference["iteration"])
metrics_data = calculate_metrics(
    case_dir=case_dir,
    room=room,
    threshold=preference["threshold"],
)

os.mkdir(host_workspace / "run/cache_result")
if metrics_data:
    with open(host_workspace / "run/cache_result/metric.json", "w") as file:
        file.write(json.dumps(metrics_data))
shutil.copytree(case_dir / "airflow", host_workspace / "run/cache_result/airflow")
shutil.copytree(case_dir / "thermal", host_workspace / "run/cache_result/thermal")

shutil.make_archive(
    host_workspace / "run/cache_result", "zip", host_workspace / "run/cache_result"
)
shutil.make_archive(host_workspace / "run/result", "zip", host_workspace / "run/result")

shutil.rmtree(host_workspace / "run/cache_result")
shutil.rmtree(host_workspace / "run/result")
