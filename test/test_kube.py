from kubernetes import config, client
import time


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
        env_vars={"hello":"hello123"},
        ttl_seconds_after_finished=60,
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
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace),
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
                                path="/Users/ryan/Repo/dcwiz/dctwin"),
                        )
                    ],
                    containers=[
                        client.V1Container(
                            name="job",
                            image=image,
                            command=command,
                            volume_mounts=[
                                client.V1VolumeMount(
                                    mount_path="/app/dctwin", name="data-volume"
                                )
                            ],
                            env=env
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


def wait_for_job(batch_api_instance, job_name, namespace="default", backoff_limit=2):
    while True:
        try:
            api_response = batch_api_instance.read_namespaced_job_status(
                name=job_name, namespace=namespace
            )
            # if successful or all retries have been exhausted, break
            print(api_response.status)
            if api_response.status.succeeded or api_response.status.failed == backoff_limit + 1:
                # if api_response.status.succeeded or not api_response.status.active:
                break
            else:
                time.sleep(1)
        except:
            time.sleep(1)


def print_job_logs(core_api_instance, job_name, namespace="default"):
    pod_list = core_api_instance.list_namespaced_pod(namespace)
    for pod in pod_list.items:
        if (
                pod.metadata.owner_references
                and pod.metadata.owner_references[0].kind == "Job"
                and pod.metadata.owner_references[0].name == job_name
        ):
            print(
                core_api_instance.read_namespaced_pod_log(pod.metadata.name, namespace)
            )


def run(
        namespace="default",
        worker_name="task-manager-worker-2",
        job_name="test-job",
        image="ghcr.io/cap-dcwiz/dctwin:0.6.29",
        command=["sh", "-c", "ping -c10 test-job-0.test-job-svc"],
):
    config.load_incluster_config()

    # Note: we need to use both the core_v1 and batch_v1 APIs. The previous one is for the pods, the latter for the jobs
    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()

    job_name = f"{worker_name}-{job_name}"

    # A PVC has been created for each worker. The suffix of the PVC name is the the worker name
    pvc_name = f"task-manager-worker-data-{worker_name}"
    pod_dns_name = f"{job_name}-0.{job_name}-svc.{namespace}.svc.cluster.local"
    backoff_limit = 2

    job = create_job_object(
        client,
        batch_v1,
        namespace=namespace,
        job_name=job_name,
        pvc_name=pvc_name,
        image=image,
        command=["bash", "-c", f"sleep infinity"],
        backoff_limit=backoff_limit,
        ttl_seconds_after_finished=60,
    )
    # print(job)

    create_service(core_v1, job_name, namespace=namespace)
    create_job(batch_v1, job)
    wait_for_job(batch_v1, job_name, namespace=namespace, backoff_limit=backoff_limit)
    print_job_logs(core_v1, namespace=namespace, job_name=job_name)

    # Delete the job.
    # Also see https://kubernetes.io/docs/concepts/workloads/controllers/ttlafterfinished/ for TTLAfterFinished if manual deletion is not desired
    # delete_job(client, batch_v1, namespace=namespace, job_name=job_name)





if __name__ == "__main__":
    run()
