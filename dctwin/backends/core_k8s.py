from pathlib import Path
from typing import Union
import uuid
import json

from dctwin.utils import config as dctwin_config
from loguru import logger
from kubernetes import config, client

from dctwin.backends.base_core import BaseBackend
from dctwin.backends.K8sJob import K8sJob

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
        job_uuid = str(uuid.uuid4())
        image = self.docker_image
        is_local_k8s = dctwin_config._environ.get("is_local_k8s", "False") == "True"
        k8s_taint = self.k8s_taint
        if is_local_k8s:
            config.load_kube_config()
            sub_path = "log/base"
        else:
            config.load_incluster_config()
            sub_path = str(case_dir).replace("/tm-data/", "", 1)
            
        volume_mount = {
            "mount_path": self.volume_data_dir,
            "sub_path": sub_path,
            }
        
        backoff_limit = 0
        ttl_seconds_after_finished=20
        job_name = f"{worker_name}-{job_uuid}"

        # Danger, do not remove this line, used by kubernetes cluster to remove container accordingly
        logger.info(f"container_id: {job_name}")

        job = K8sJob(
                name=job_uuid,
                image=image,
                command=command,
                working_dir_in_volume=working_dir,
                worker_name=worker_name,
                need_service=False,
                need_volume=True,
                start=True,
                env_vars=environment,
                namespace=namespace,
                resources=cfd_resources,
                is_local_k8s=is_local_k8s,
                local_volume_path=DEFAULT_LOCAL_VOLUME_PATH,
                k8s_taint=k8s_taint,
                volume_mount=volume_mount,
                additional_params={
                    "spec.ttl_seconds_after_finished": ttl_seconds_after_finished,
                    "spec.backoff_limit": backoff_limit,
                })
        stream_log = job.stream()
        if background:
            return None
        if stream:
            return stream_log
        else:
            for line in stream_log:
                logger.info(str(line))
        job.clean()
