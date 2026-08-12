import logging
import os

from kubernetes import config

logger = logging.getLogger(__name__)

NAMESPACE_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
KUBERNETES_NAMESPACE_ENVVAR = "KUBERNETES_NAMESPACE"


def load_kubernetes_config() -> str:
    """Load Kubernetes config and determine the current namespace."""
    try:
        config.load_incluster_config()
        with open(NAMESPACE_PATH) as f:
            namespace = f.read().strip()
    except config.ConfigException:
        config.load_kube_config()
        _, current_context = config.list_kube_config_contexts()
        try:
            namespace = current_context["context"]["namespace"]
        except KeyError:
            namespace = "default"

    os.environ[KUBERNETES_NAMESPACE_ENVVAR] = namespace
    logger.info(f"Kubernetes namespace: {namespace}")
    return namespace
