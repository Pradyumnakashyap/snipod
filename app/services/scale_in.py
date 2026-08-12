import logging
import time
import typing as t
from contextlib import contextmanager
from http import HTTPStatus

from fastapi import HTTPException, status
from kubernetes.client import ApiException, AppsV1Api, CoreV1Api, V1Pod, V1Scale

logger = logging.getLogger(__name__)

ANNOTATION_POD_DELETION_COST = "controller.kubernetes.io/pod-deletion-cost"


def get_pod(namespace: str, name: str) -> V1Pod:
    try:
        return CoreV1Api().read_namespaced_pod(name=name, namespace=namespace)
    except ApiException as error:
        if error.status == HTTPStatus.NOT_FOUND:
            logger.warning(f"Pod '{name}' not found in namespace '{namespace}' — cannot scale in a non-existent pod")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pod '{name}' not found in namespace '{namespace}'",
            ) from error
        logger.error(f"Kubernetes API error getting pod '{name}' in '{namespace}': {error.status} {error.reason}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pod '{name}': {error.reason}",
        ) from error


def find_owning_deployment(pod: V1Pod) -> str:
    """
    Walk ownerReferences: Pod -> ReplicaSet -> Deployment.
    Returns the Deployment name.
    """
    metadata = pod.metadata
    namespace = metadata.namespace

    if not metadata.owner_references:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pod '{metadata.name}' has no ownerReferences",
        )

    for ref in metadata.owner_references:
        if ref.kind == "ReplicaSet":
            try:
                rs = AppsV1Api().read_namespaced_replica_set(name=ref.name, namespace=namespace)
                if rs.metadata.owner_references:
                    for rs_ref in rs.metadata.owner_references:
                        if rs_ref.kind == "Deployment":
                            return rs_ref.name
            except ApiException as error:
                logger.error(f"Failed to read ReplicaSet '{ref.name}': {error.reason}")

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReplicaSet '{ref.name}' has no owning Deployment",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Pod '{metadata.name}' is not owned by a Deployment (via ReplicaSet)",
    )


def is_already_terminating(pod: V1Pod) -> bool:
    metadata = pod.metadata
    if metadata.deletion_timestamp is not None:
        return True
    annotations = metadata.annotations or {}
    return str(annotations.get(ANNOTATION_POD_DELETION_COST)) == "-1"


def set_pod_deletion_cost(namespace: str, name: str, cost: str) -> V1Pod:
    return CoreV1Api().patch_namespaced_pod(
        name=name,
        namespace=namespace,
        body={"metadata": {"annotations": {ANNOTATION_POD_DELETION_COST: cost}}},
    )


@contextmanager
def mark_pod_for_deletion(namespace: str, name: str):
    """Mark a pod with deletion-cost -1 so the controller picks it for removal."""
    pod = get_pod(namespace, name)
    old_cost = (pod.metadata.annotations or {}).get(ANNOTATION_POD_DELETION_COST)

    set_pod_deletion_cost(namespace, name, "-1")
    try:
        yield
    except Exception as error:
        # Revert annotation on failure
        try:
            set_pod_deletion_cost(namespace, name, old_cost or "0")
        except Exception as revert_error:
            logger.error(f"Failed to revert pod-deletion-cost on '{name}': {revert_error}")
        raise error


def scale_down_deployment(namespace: str, deployment_name: str, max_retries: int = 5, backoff: float = 0.2) -> None:
    """Decrease replicas by 1 on the owning Deployment."""
    api = AppsV1Api()

    for attempt in range(1, max_retries + 1):
        try:
            scale: V1Scale = api.read_namespaced_deployment_scale(name=deployment_name, namespace=namespace)

            if scale.spec.replicas <= 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot scale Deployment '{deployment_name}' below 1 replica",
                )

            scale.spec.replicas -= 1
            api.replace_namespaced_deployment_scale(name=deployment_name, namespace=namespace, body=scale)
            return

        except ApiException as error:
            if error.status == HTTPStatus.CONFLICT and attempt < max_retries:
                logger.warning(f"Conflict scaling Deployment/{deployment_name}, retry {attempt}/{max_retries}")
                time.sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to scale Deployment '{deployment_name}': {error.reason}",
            ) from error

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Max retries reached scaling Deployment '{deployment_name}'",
    )


def handle_scale_in(namespace: str, pod_name: str) -> t.Dict[str, str]:
    """
    Main handler: find the pod's owning Deployment, mark the pod for deletion, scale down.
    """
    pod = get_pod(namespace, pod_name)

    deployment_name = find_owning_deployment(pod)

    if is_already_terminating(pod):
        logger.info(f"Pod '{pod_name}' is already terminating, skipping scale-in")
        return {"deployment_name": deployment_name}

    logger.info(f"Scaling in Deployment/{deployment_name} by removing pod '{pod_name}'")

    with mark_pod_for_deletion(namespace, pod_name):
        scale_down_deployment(namespace, deployment_name)

    return {"deployment_name": deployment_name}
