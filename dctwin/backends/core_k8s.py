from pathlib import Path
from typing import Union, Any
import time
import uuid
import os
import json

from dctwin.utils import config as dctwin_config
from loguru import logger
from kubernetes import config, client

from dctwin.backends.base_core import BaseBackend


# Constants
DEFAULT_NAMESPACE = "default"
DEFAULT_JOB_NAME = "test-job"
DEFAULT_PVC_NAME = "task-manager-worker-data-task-manager-worker-0"
DEFAULT_IMAGE = "ubuntu"
DEFAULT_COMMAND = ["sleep", "1000"]
DEFAULT_BACKOFF_LIMIT = 0
DEFAULT_ENV_VARS = {}
DEFAULT_TTL_SECONDS_AFTER_FINISHED = 30
DEFAULT_VOLUME_DATA_DIR = "/data"
DEFAULT_LOCAL_VOLUME_PATH = "/tm-data/"


def delete_job(api_instance, namespace=DEFAULT_NAMESPACE, job_name=DEFAULT_JOB_NAME):
    api_instance.delete_namespaced_job(
        name=job_name,
        namespace=namespace,
        body=client.V1DeleteOptions(
            propagation_policy="Foreground", grace_period_seconds=5
        ),
    )
    while True:
        try:
            api_instance.read_namespaced_job(name=job_name, namespace=namespace)
            time.sleep(1)
        except:
            break


def create_job_object(
    api_instance,
    cfd_resources,
    namespace=DEFAULT_NAMESPACE,
    job_name=DEFAULT_JOB_NAME,
    pvc_name=DEFAULT_PVC_NAME,
    image=DEFAULT_IMAGE,
    command=DEFAULT_COMMAND,
    backoff_limit=DEFAULT_BACKOFF_LIMIT,
    env_vars=DEFAULT_ENV_VARS,
    ttl_seconds_after_finished=DEFAULT_TTL_SECONDS_AFTER_FINISHED,
    working_dir=None,
    case_dir=None,
    volume_data_dir=DEFAULT_VOLUME_DATA_DIR,
    k8s_taint="",
):
    try:
        delete_job(api_instance, namespace=namespace, job_name=job_name)
    except:
        print("Job does not exist. Creating new job")

    env = [client.V1EnvVar(name=key, value=item) for key, item in env_vars.items()]
    IS_LOCAL_K8S = dctwin_config._environ.get("is_local_k8s", "False") == "True"
    local_volume_path = DEFAULT_LOCAL_VOLUME_PATH  # New parameter for local volume path

    if IS_LOCAL_K8S:
        volumes = [
            client.V1Volume(
                name="data-volume",
                host_path=client.V1HostPathVolumeSource(
                    path=local_volume_path  # Path to the local volume
                ),
            )
        ]
        volume_mounts = [
            client.V1VolumeMount(
                mount_path=volume_data_dir, name="data-volume", sub_path="log/base"
            )
        ]

    else:
        volumes = [
            client.V1Volume(
                name="data-volume",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=pvc_name
                ),
            )
        ]
        volume_mounts = [
            client.V1VolumeMount(
                mount_path=volume_data_dir,
                name="data-volume",
                sub_path=str(case_dir).replace("/tm-data/", "", 1),
            )
        ]

    tolerations = []
    if k8s_taint != "":
        key, value, effect = k8s_taint.split(":")
        toleration = client.V1Toleration(
            effect=effect, key=key, operator="Equal", value=value
        )
        tolerations.append(toleration)

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    subdomain=f"{job_name}-svc",
                    image_pull_secrets=[client.V1LocalObjectReference(name="regcred")],
                    volumes=volumes,
                    containers=[
                        client.V1Container(
                            name="job",
                            image=image,
                            command=command,
                            volume_mounts=volume_mounts,
                            env=env,
                            working_dir=working_dir,
                            resources=client.V1ResourceRequirements(
                                requests=cfd_resources,
                                limits=cfd_resources,
                            ),
                        )
                    ],
                    tolerations=tolerations,
                    restart_policy="Never",
                )
            ),
            backoff_limit=backoff_limit,
            completion_mode="Indexed",
            ttl_seconds_after_finished=ttl_seconds_after_finished,
        ),
    )
    return job


def create_job(batch_api_instance, job):
    namespace = job.metadata.namespace
    batch_api_instance.create_namespaced_job(namespace=namespace, body=job)


def wait_for_job(
    batch_api_instance,
    core_api_instance,
    job_name,
    namespace=DEFAULT_NAMESPACE,
    backoff_limit=DEFAULT_BACKOFF_LIMIT,
):
    while True:
        try:
            api_response = batch_api_instance.read_namespaced_job_status(
                name=job_name, namespace=namespace
            )

            if api_response.status.ready != 1:
                time.sleep(1)
                continue
            pod_list = core_api_instance.list_namespaced_pod(namespace)
            for pod in pod_list.items:
                if (
                    pod.metadata.owner_references
                    and pod.metadata.owner_references[0].kind == "Job"
                    and pod.metadata.owner_references[0].name == job_name
                ):
                    return core_api_instance.read_namespaced_pod_log(
                        pod.metadata.name,
                        namespace,
                        follow=True,
                        _preload_content=False,
                    ).stream()
            if (
                api_response.status.succeeded
                or api_response.status.failed == backoff_limit + 1
            ):
                break
            else:
                time.sleep(2)
        except:
            time.sleep(1)


class BackendK8s(BaseBackend):
    def __init__(self, k8s_config=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.k8s_config = k8s_config
        # get from k8s config
        self.namespace = k8s_config.get("k8s_namespace", "default")
        self.worker_name = k8s_config.get("worker_name", "default-worker")
        self.k8s_taint = k8s_config.get("k8s_taint", "")
        self.cfd_resources = json.loads(
            k8s_config.get(
                "cfd_resources",
                json.dumps(
                    {"cpu": "16000m", "memory": "4Gi", "ephemeral-storage": "1000Mi"}
                ),
            )
        )

    def run_container(
        self,
        case_dir: Union[Path, str],
        environment: dict = {},
        stream: bool = False,
        working_dir: str = None,
        command: list = None,
        background: bool = False,
        **kwargs,
    ) -> None:
        command = self.command if command is None else command
        logger.info(f"docker mount: {case_dir}")
        logger.info("docker run: " + (" ".join(command)))
        if working_dir is None:
            working_dir = self.volume_data_dir
        namespace = self.namespace
        worker_name = self.worker_name
        cfd_resources = self.cfd_resources
        job_name = uuid.uuid4()
        image = self.docker_image
        IS_LOCAL_K8S = dctwin_config._environ.get("is_local_k8s", "False") == "True"
        if IS_LOCAL_K8S:
            config.load_kube_config()
        else:
            config.load_incluster_config()

        core_v1 = client.CoreV1Api()
        batch_v1 = client.BatchV1Api()

        job_name = f"{worker_name}-{job_name}"
        pvc_name = f"task-manager-worker-data-{worker_name}"
        backoff_limit = 0
        logger.info(f"container_id: {job_name}")

        job = create_job_object(
            batch_v1,
            cfd_resources,
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
            volume_data_dir=self.volume_data_dir,
            k8s_taint=self.k8s_taint,
        )

        create_job(batch_v1, job)
        time.sleep(2)
        if background:
            return None
        stream_log = wait_for_job(
            batch_v1,
            core_v1,
            job_name,
            namespace=namespace,
            backoff_limit=backoff_limit,
        )
        if stream:
            return stream_log
        else:
            for line in stream_log:
                logger.info(line.decode("utf-8").splitlines())
