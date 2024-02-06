import logging

from kubernetes import client
import time
import socket


class K8sJob:
    # Some default parameters for the job.
    # One can subclass this class and override this dict to avoid specifying the same parameters every time.
    # It can still be overriden by the "additional_params" argument
    DEFAULT_PARAMS = {}
    DEFAULT_NAMESPACE = "dcwiz"
    DEFAULT_WORKING_DIR_IN_VOLUME = "dcwiz_tasks"
    DEFAULT_RESOURCES = {
        "cpu": "100m",
        "memory": "100Mi",
        "ephemeral-storage": "100Mi",
    }
    DEFAULT_VOLUME_MOUNT = {
       "mount_path": "/tm-data",
        "sub_path": "",
    }
    DEFAULT_K8S_TAINT = ""

    def __init__(
        self,
        image,
        command=None,  # The command to run in the container. If None, the default command is used
        name="unnamed-job",  # The name of the job. If None, the job is named as "unnamed-job"
        need_service=False,  # Whether a service is needed for the job to communicate with each other
        need_volume=False,
        # Whether the job needs the shared volume. If false, the "working_dir_in_volume" is ignored
        working_dir_in_volume=DEFAULT_WORKING_DIR_IN_VOLUME,
        # The working directory in the volume. The default is the folder containing "conf", "data", "tasks", etc.
        resources=DEFAULT_RESOURCES,  # The resources for the job. If None, the default resources are used
        namespace=DEFAULT_NAMESPACE,
        ports=None,
        start=True,
        log_interval=5,
        env_vars={},
        worker_name=None,
        is_local_k8s=False,
        local_volume_path=None, # The local path to the volume, must set if is_local_k8s is True
        k8s_taint=DEFAULT_K8S_TAINT, # The taint for the job, e.g. "key:value
        volume_mount=DEFAULT_VOLUME_MOUNT,  # The volume mount for the job. If None, the default volume is used
        additional_params=None,  # Additional parameters for the job, e.g. ttl_seconds_after_finished
    ) -> None:
        self._core_api_ins = None
        self._batch_api_ins = None

        self.image = image
        self.command = command
        self.name = name
        self.need_service = need_service
        self.need_volume = need_volume
        self.working_dir_in_volume = working_dir_in_volume
        self.resources = resources
        self.namespace = namespace
        self.ports = ports
        self.log_interval = log_interval
        self.env_vars = env_vars
        self.is_local_k8s = is_local_k8s
        self.local_volume_path = local_volume_path
        self.k8s_taint = k8s_taint
        self.volume_mount = volume_mount
        self.additional_params = self._parse_additional_params(
            self.DEFAULT_PARAMS | (additional_params or {})
        )
        if worker_name is not None:
            self.worker_name = worker_name
        else:
            self.worker_name = socket.gethostname()

        self._cleaned = False
        self._status_cache = None

        if start:
            self.start()

    @staticmethod
    def _parse_additional_params(job_params):
        container_additional_args = {}
        tmpl_spec_additional_args = {}
        tmpl_additional_args = {}
        spec_additional_args = dict(backoff_limit=2, ttl_seconds_after_finished=60)
        job_additional_args = {}
        for k, v in job_params.items():
            if k.startswith("spec.template.spec.containers."):
                idx = int(k.split(".")[-2])
                container_additional_args.setdefault(idx, {})[k.split(".")[-1]] = v
            elif k.startswith("sepc.template.spec"):
                tmpl_spec_additional_args[k.split(".")[-1]] = v
            elif k.startswith("spec.template"):
                tmpl_additional_args[k.split(".")[-1]] = v
            elif k.startswith("spec"):
                spec_additional_args[k.split(".")[-1]] = v
            else:
                job_additional_args[k] = v
        return {
            ".": job_additional_args,
            "spec": spec_additional_args,
            "spec.template": tmpl_additional_args,
            "spec.template.spec": tmpl_spec_additional_args,
            "spec.template.spec.containers": container_additional_args,
        }

    @staticmethod
    def manual_clean(job_name, namespace):
        batch_api = client.BatchV1Api()
        batch_api.delete_namespaced_job(
            name=job_name,
            namespace=namespace,
            body=client.V1DeleteOptions(
                propagation_policy="Foreground", grace_period_seconds=5
            ),
        )

    def start(self):
        # delete the job if it already exists
        try:
            self.clean()
        except:
            pass
        job = self._create_job_object()
        if self.need_service:
            self._create_service()
        self._batch_api.create_namespaced_job(namespace=self.namespace, body=job)

    @property
    def status(self):
        try:
            self._status_cache = self._batch_api.read_namespaced_job_status(
                name=self.full_name, namespace=self.namespace
            ).status
        except Exception as e:
            logging.debug(f"Cannot get status of job {self.full_name}: {str(e)}")
            return None
        return self._status_cache

    def is_completed_or_failed(self):
        status = self.status
        if not status:
            return True
        backoff_limit = self.additional_params["spec"]["backoff_limit"]
        return status.succeeded or status.failed == backoff_limit + 1

    def stream(self):
        # This function return a generator that yields the log lines of the job until the job is completed or failed
        # (backoff_limit+1) times
        logged_pods = set()
        while True:
            try:
                if self.is_completed_or_failed():
                    break
                else:
                    pods = self._get_job_pods(exclude_pods=logged_pods)
                    if pods:
                        yield from self._stream_pods_logs(pods)
                        logged_pods.update(pod.metadata.name for pod in pods)
                    else:
                        time.sleep(1)
            # except SystemExit:
            #     break
            except Exception as e:
                # Eat the exception and continue as we need to read other pods
                logging.debug(f"Exception when streaming logs: {str(e)}")
                time.sleep(1)

    def join(self):
        """Wait for the job to complete or fail (backoff_limit+1) times"""
        while True:
            try:
                if self.is_completed_or_failed():
                    break
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(1)

    def clean(self):
        batch_api = self._batch_api
        try:
            batch_api.delete_namespaced_job(
                name=self.full_name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    propagation_policy="Foreground", grace_period_seconds=5
                ),
            )
        except Exception as e:
            logging.debug(f"Cannot delete job {self.full_name}: {str(e)}")

        # wait for the job to be deleted
        while True:
            try:
                batch_api.read_namespaced_job(
                    name=self.full_name, namespace=self.namespace
                )
                time.sleep(1)
            except Exception:
                break

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.clean()

    @property
    def _core_api(self):
        if not self._core_api_ins:
            self._core_api_ins = client.CoreV1Api()
        return self._core_api_ins

    @property
    def _batch_api(self):
        if not self._batch_api_ins:
            self._batch_api_ins = client.BatchV1Api()
        return self._batch_api_ins

    @property
    def full_name(self):
        return f"{self.worker_name}-{self.name}"

    @property
    def pvc_name(self):
        return f"task-manager-worker-data-{self.worker_name}"

    @property
    def working_dir_in_container(self):
        if self.working_dir_in_volume.startswith("/"):
            return self.working_dir_in_volume
        else:
            return f"/tm-data/{self.working_dir_in_volume.lstrip('/')}"

    @property
    def service_name(self):
        return f"{self.full_name}-svc"

    @property
    def pod_dns_name(self):
        return f"{self.full_name}-0.{self.full_name}-svc.{self.namespace}.svc.cluster.local"

    def _create_job_object(self):
        container_args = dict(name="job", image=self.image)
        tmpl_spec_args = dict(restart_policy="Never")
        env = []
        for key, item in self.env_vars.items():
            env.append(client.V1EnvVar(name=key, value=item))
        container_args["env"] = env

        if self.command is not None:
            container_args["command"] = self.command

        if self.need_volume:
            if self.is_local_k8s:
                tmpl_spec_args["volumes"] = [
                    client.V1Volume(
                        name="data-volume",
                        host_path=client.V1HostPathVolumeSource(
                            path=self.local_volume_path
                        ),
                    )
                ]

            else:
                tmpl_spec_args["volumes"] = [
                    client.V1Volume(
                        name="data-volume",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=self.pvc_name
                        ),
                    )
                ]
            container_args["volume_mounts"] = [
                client.V1VolumeMount(
                    mount_path=self.volume_mount["mount_path"],
                    name="data-volume",
                    sub_path=self.volume_mount["sub_path"],
                ),
            ]
            container_args["working_dir"] = self.working_dir_in_container

        tolerations = []
        if self.k8s_taint != "":
            key, value, effect = self.k8s_taint.split(":")
            toleration = client.V1Toleration(
                effect=effect, key=key, operator="Equal", value=value
            )
            tolerations.append(toleration)
        tmpl_spec_args["tolerations"] = tolerations

        if self.resources is not None:
            final_resources = client.V1ResourceRequirements(requests=self.resources,limits=self.resources)
            container_args["resources"] = final_resources

        if self.need_service:
            tmpl_spec_args["subdomain"] = self.service_name

        container_args.update(
            self.additional_params["spec.template.spec.containers"].get(0, {})
        )
        tmpl_spec_args["containers"] = [client.V1Container(**container_args)]

        pod_spec = client.V1PodSpec(
            **tmpl_spec_args | self.additional_params["spec.template.spec"]
        )
        pod_spec.image_pull_secrets = [client.V1LocalObjectReference(name="regcred")]

        # Configure Pod template container
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=self.full_name,
                namespace=self.namespace,
                labels=dict(
                    category="dcwiz", job_name=self.name
                ),  # So that when down or restarting, the job can be found and cleaned up
            ),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(
                    spec=pod_spec,
                    **self.additional_params["spec.template"],
                ),
                completion_mode="Indexed",
                **self.additional_params["spec"],
            ),
            **self.additional_params["."],
        )
        return job

    def _create_service(self):
        # Create a headless service for the job to communicate with each other.
        # The service name is the same as the "{job_name}-svc"
        # Before creating the service, we need to delete it if it already exists
        core_api = self._core_api
        try:
            core_api.delete_namespaced_service(
                name=self.service_name, namespace=self.namespace
            )
        except:
            pass
        core_api.create_namespaced_service(
            namespace=self.namespace,
            body=client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(name=self.service_name),
                spec=client.V1ServiceSpec(
                    cluster_ip="None",
                    selector={"job-name": self.full_name},
                    ports=[client.V1ServicePort(port=p) for p in (self.ports or [80])],
                ),
            ),
        )

    def _get_job_pods(self, exclude_pods=()):
        pod_list = self._core_api.list_namespaced_pod(self.namespace)
        return [
            pod
            for pod in pod_list.items
            if pod.metadata.owner_references
            and pod.metadata.owner_references[0].kind == "Job"
            and pod.metadata.owner_references[0].name == self.full_name
            and pod.metadata.name not in exclude_pods
        ]

    def _stream_pods_logs(self, pods):
        last_line = {}
        while True:
            time.sleep(self.log_interval)
            for pod in pods:
                logs = self._core_api.read_namespaced_pod_log(
                    pod.metadata.name,
                    self.namespace,
                    since_seconds=self.log_interval + 5,
                )
                lines = logs.splitlines()
                pod_name = pod.metadata.name
                if pod_name in last_line:
                    if last_line[pod_name] in lines:
                        last_line_index = lines.index(last_line[pod_name]) + 1
                        lines = lines[last_line_index:]
                if lines:
                    last_line[pod_name] = lines[-1]
                    for line in lines:
                        yield line
            if self.is_completed_or_failed():
                break
