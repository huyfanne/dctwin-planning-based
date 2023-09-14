import abc
from pathlib import Path

from loguru import logger
from typing import Union

from docker import DockerClient, from_env
from docker.errors import ContainerError, ImageNotFound

from dctwin.utils import config
from kubernetes import config, client
from kubernetes.stream import stream
import time
import uuid


def delete_job(client, api_instance, namespace="default", job_name="test-job"):
    api_response = api_instance.delete_namespaced_job(
        name=job_name,
        namespace=namespace,
        body=client.V1DeleteOptions(
            propagation_policy="Foreground", grace_period_seconds=5
        ),
    )
    print("Job deleted. status='%s'" % str(api_response.status))
    # wait for the job to be deleted
    while True:
        try:
            api_response = api_instance.read_namespaced_job(
                name=job_name, namespace=namespace
            )
            time.sleep(1)
        except:
            break


def create_service(core_api, job_name, namespace="dcwiz", ports=None):
    # Create a headless service for the job to communicate with each other.
    # The service name is the same as the "{job_name}-svc"
    # Before creating the service, we need to delete it if it already exists
    service_name = f"{job_name}-svc"
    try:
        print("Deleting existing service")
        core_api.delete_namespaced_service(
            name=service_name, namespace=namespace
        )
    except:
        print("Service does not exist. Creating new service")
    core_api.create_namespaced_service(
        namespace=namespace,
        body=client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(name=service_name),
            spec=client.V1ServiceSpec(
                cluster_ip=None,
                selector={"job-name": job_name},
                ports=[client.V1ServicePort(port=p) for p in (ports or [80])],
            ),
        ),
    )


def create_job_object(
        client,
        api_instance,
        namespace="default",
        job_name="test-job",
        pvc_name="task-manager-worker-data-task-manager-worker-0",
        image="ubuntu",
        command=["ls", "-al", "/tm-data/"],
        backoff_limit=2,
        env_vars={},
        ttl_seconds_after_finished=60,
        working_dir = None,
        case_dir = None,
        volume_data_dir = "/data"
):
    # delete the job if it already exists
    try:
        delete_job(api_instance, namespace=namespace, job_name=job_name)
    except:
        print("Job does not exist. Creating new job")

    env = []
    for key, item in env_vars.items():
        env.append(client.V1EnvVar(name=key, value=item))

    # Configureate Pod template container
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace, labels={
            "category": "test123"
        }),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    subdomain=f"{job_name}-svc",
                    image_pull_secrets=[
                        client.V1LocalObjectReference(name="regcred")
                    ],
                    volumes=[
                        client.V1Volume(
                            name="data-volume",
                            host_path=client.V1HostPathVolumeSource(
                                path=str(case_dir)),
                        )
                    ],
                    containers=[
                        client.V1Container(
                            name="job",
                            image=image,
                            command=command,
                            volume_mounts=[
                                client.V1VolumeMount(
                                    mount_path=volume_data_dir, name="data-volume"
                                )
                            ],
                            env=env,
                            working_dir=working_dir,
                            resources=client.V1ResourceRequirements(
                                requests={"cpu": "3000m", "memory": "900Mi", "ephemeral-storage": "100Mi"},
                                limits={"cpu": "3000m", "memory": "900Mi", "ephemeral-storage": "100Mi"},
                            ),
                        )
                    ],
                    restart_policy="Never",
                )
            ),
            backoff_limit=backoff_limit,  # number of retries (+1 for the initial run)
            completion_mode="Indexed",
            # ttl_seconds_after_finished=ttl_seconds_after_finished,
        ),
    )
    return job


def create_job(batch_api_instance, job):
    namespace = job.metadata.namespace

    api_response = batch_api_instance.create_namespaced_job(
        namespace=namespace, body=job
    )
    print("Job created. status='%s'" % str(api_response.status))


def wait_for_job(batch_api_instance, core_api_instance, job_name, namespace="default", backoff_limit=2):

    while True:
        try:
            api_response = batch_api_instance.read_namespaced_job_status(
                name=job_name, namespace=namespace
            )
            pod_list = core_api_instance.list_namespaced_pod(namespace)
            for pod in pod_list.items:
                if (
                        pod.metadata.owner_references
                        and pod.metadata.owner_references[0].kind == "Job"
                        and pod.metadata.owner_references[0].name == job_name
                ):
                    for line in core_api_instance.read_namespaced_pod_log(pod.metadata.name, namespace, follow=True,
                                                                         _preload_content=False).stream():
                        print(line)

            if api_response.status.succeeded or api_response.status.failed == backoff_limit + 1:
                # if api_response.status.succeeded or not api_response.status.active:
                break
            else:
                time.sleep(2)
        except:
            time.sleep(1)




class BackendK8s(abc.ABC):
    """
    Base class for DCTwin Backend. All backend should inherit this class.
    The Backend is to support the simulation of various simulators (EnergyPlus, OpenFoam, etc.) which is dockerized.
    It mainly takes care of the following tasks:
    1. Check the docker image of specific simulator
    2. Run the docker container of specific simulator

    :param client: docker client
    :param process_num: number of cores for simulation
    """
    volume_data_dir = "/data"
    volume_geometry_dir = f"{volume_data_dir}/constant/triSurface"

    def __init__(self, process_num: int = 1) -> None:
        self.process_num = process_num
        self.container = None

    @property
    @abc.abstractmethod
    def docker_image(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def command(self) -> Union[list, str]:
        pass

    @abc.abstractmethod
    def run(self, **kwargs) -> None:
        pass


    def run_container(
        self,
        case_dir: Union[Path, str],
        environment: dict = {},
        auto_remove: bool = True,
        user: int = None,
        working_dir: str = None,
        stream: bool = False,
        command: list = None,
        background: bool = False,
        **kwargs,
    ) -> None:
        command = self.command if command is None else command
        logger.info(f"docker mount: {case_dir}")
        logger.info("docker run: " + (" ".join(command)))
        if working_dir is None:
            working_dir = self.volume_data_dir

        # kube start
        namespace = "default"
        worker_name = "task-manager-worker-22"
        job_name = uuid.uuid4()
        image = self.docker_image
        config.load_incluster_config()
        # Note: we need to use both the core_v1 and batch_v1 APIs. The previous one is for the pods, the latter for the jobs
        core_v1 = client.CoreV1Api()
        batch_v1 = client.BatchV1Api()

        job_name = f"{worker_name}-{job_name}"
        pvc_name = f"task-manager-worker-data-{worker_name}"
        pod_dns_name = f"{job_name}-0.{job_name}-svc.{namespace}.svc.cluster.local"
        print("helo")
        print(case_dir)
        print(working_dir)
        print(self.volume_data_dir)
        backoff_limit = 2
        print(command)
        if isinstance(command, str):
            command =  [command]
        print(command)

        job = create_job_object(
            client,
            batch_v1,
            namespace=namespace,
            job_name=job_name,
            pvc_name=pvc_name,
            image=image,
            # command=command,
            command=["bash", "-c", f"sleep infinity"],
            backoff_limit=backoff_limit,
            ttl_seconds_after_finished=60,
            env_vars=environment,
            working_dir=working_dir,
            case_dir=case_dir,
            volume_data_dir=self.volume_data_dir
        )

        create_service(core_v1, job_name, namespace=namespace)
        create_job(batch_v1, job)
        wait_for_job(batch_v1,core_v1, job_name, namespace=namespace, backoff_limit=backoff_limit)


        # kube end


        # command = self.command if command is None else command
        # logger.info(f"docker mount: {case_dir}")
        # logger.info("docker run: " + (" ".join(command)))
        # try:
        #     self.client.close()
        #     self.container = self.client.containers.run(
        #         self.docker_image,
        #         command=command,
        #         auto_remove=auto_remove,
        #         volumes={
        #             str(case_dir): {
        #                 "bind": self.volume_data_dir,
        #                 "mode": "rw",
        #             },
        #             "/etc/passwd": {
        #                 "bind": "/etc/passwd",
        #                 "mode": "ro",
        #             },
        #         },
        #         user=user,
        #         environment=environment,
        #         working_dir=working_dir
        #         if working_dir is not None else self.volume_data_dir,
        #         detach=True,
        #         **kwargs,
        #     )
        #     if background:
        #         return None
        #     output_stream = self.container.logs(stream=True, follow=True)
        #     # do not change this container_id log, the worker are depending on this to get the container id
        #     logger.info(f"container_id: {self.container.id}")
        #     if stream:
        #         return output_stream
        #     else:
        #         for log in output_stream:
        #             if config.BACKEND_LOG_PRINT:
        #                 logger.info(log.decode("utf-8").strip())
        # except ContainerError as e:
        #     logger.info(str(e.stderr))
        #     raise e
