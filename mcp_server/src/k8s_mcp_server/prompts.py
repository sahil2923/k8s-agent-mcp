"""Build kubectl command strings from structured instruction parameters."""

from typing import Optional


def _namespace_flag(namespace: Optional[str], all_namespaces: bool = False) -> str:
    if all_namespaces:
        return " -A"
    if namespace:
        return f" -n {namespace}"
    return ""


# --- List & get ---


def k8s_resource_status(
    resource_type: str,
    namespace: str = "default",
    all_namespaces: bool = False,
    label_selector: str = "",
    field_selector: str = "",
) -> str:
    flags = _namespace_flag(namespace, all_namespaces)
    if label_selector:
        flags += f" -l {label_selector}"
    if field_selector:
        flags += f" --field-selector={field_selector}"
    return f"kubectl get {resource_type}{flags}"


def get_resource(
    resource_type: str,
    name: str,
    namespace: str = "default",
    output: str = "",
) -> str:
    o = f" -o {output}" if output else ""
    return f"kubectl get {resource_type} {name}{_namespace_flag(namespace)}{o}"


def get_all_namespaces() -> str:
    return "kubectl get namespaces"


def get_nodes(wide: bool = True) -> str:
    return "kubectl get nodes -o wide" if wide else "kubectl get nodes"


def get_cluster_info() -> str:
    return "kubectl cluster-info"


def get_api_resources() -> str:
    return "kubectl api-resources"


def get_contexts() -> str:
    return "kubectl config get-contexts"


def get_current_context() -> str:
    return "kubectl config current-context"


# --- Describe ---


def describe_resource(
    resource_type: str,
    name: str,
    namespace: str = "default",
) -> str:
    return f"kubectl describe {resource_type} {name}{_namespace_flag(namespace)}"


def describe_pod(pod_name: str, namespace: str = "default") -> str:
    return describe_resource("pod", pod_name, namespace)


def describe_service(service_name: str, namespace: str = "default") -> str:
    return describe_resource("service", service_name, namespace)


def describe_deployment(deployment_name: str, namespace: str = "default") -> str:
    return describe_resource("deployment", deployment_name, namespace)


def describe_node(node_name: str) -> str:
    return f"kubectl describe node {node_name}"


def describe_ingress(ingress_name: str, namespace: str = "default") -> str:
    return describe_resource("ingress", ingress_name, namespace)


def describe_configmap(configmap_name: str, namespace: str = "default") -> str:
    return describe_resource("configmap", configmap_name, namespace)


def describe_pvc(pvc_name: str, namespace: str = "default") -> str:
    return describe_resource("pvc", pvc_name, namespace)


# --- Pods: logs, debug, exec ---


def get_pod(pod_name: str, namespace: str = "default") -> str:
    return get_resource("pod", pod_name, namespace)


def get_pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: str = "",
    tail_lines: str = "100",
    previous: bool = False,
    follow: bool = False,
) -> str:
    parts = [f"kubectl logs {pod_name}{_namespace_flag(namespace)}"]
    if container:
        parts.append(f"-c {container}")
    if tail_lines:
        parts.append(f"--tail={tail_lines}")
    if previous:
        parts.append("--previous")
    if follow:
        parts.append("-f")
    return " ".join(parts)


def get_pod_yaml(pod_name: str, namespace: str = "default") -> str:
    return get_resource("pod", pod_name, namespace, output="yaml")


def get_resource_yaml(
    resource_type: str,
    name: str,
    namespace: str = "default",
) -> str:
    return get_resource(resource_type, name, namespace, output="yaml")


def exec_pod(
    pod_name: str,
    command: str,
    namespace: str = "default",
    container: str = "",
) -> str:
    c = f"-c {container} " if container else ""
    return f"kubectl exec {pod_name}{_namespace_flag(namespace)} {c}-- {command}"


# --- Events & troubleshooting ---


def get_events(
    namespace: str = "default",
    all_namespaces: bool = False,
    field_selector: str = "",
) -> str:
    flags = _namespace_flag(namespace, all_namespaces)
    if field_selector:
        flags += f" --field-selector={field_selector}"
    return f"kubectl get events{flags} --sort-by=.lastTimestamp"


def get_pod_events(pod_name: str, namespace: str = "default") -> str:
    return get_events(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name}",
    )


def top_pods(namespace: str = "default", all_namespaces: bool = False) -> str:
    return f"kubectl top pods{_namespace_flag(namespace, all_namespaces)}"


def top_nodes() -> str:
    return "kubectl top nodes"


# --- Services & networking ---


def get_endpoints(
    name: str = "",
    namespace: str = "default",
) -> str:
    target = f" {name}" if name else ""
    return f"kubectl get endpoints{target}{_namespace_flag(namespace)}"


def get_service(service_name: str, namespace: str = "default") -> str:
    return get_resource("service", service_name, namespace)


def get_ingress(namespace: str = "default", all_namespaces: bool = False) -> str:
    return k8s_resource_status("ingress", namespace, all_namespaces)


# --- Workloads: deployments, rollout ---


def get_deployment(deployment_name: str, namespace: str = "default") -> str:
    return get_resource("deployment", deployment_name, namespace)


def get_replicasets(namespace: str = "default", label_selector: str = "") -> str:
    return k8s_resource_status("replicasets", namespace, label_selector=label_selector)


def scale_deployment(
    deployment_name: str,
    replicas: int,
    namespace: str = "default",
) -> str:
    return (
        f"kubectl scale deployment {deployment_name} "
        f"--replicas={replicas}{_namespace_flag(namespace)}"
    )


def rollout_status(deployment_name: str, namespace: str = "default") -> str:
    return f"kubectl rollout status deployment/{deployment_name}{_namespace_flag(namespace)}"


def rollout_restart(deployment_name: str, namespace: str = "default") -> str:
    return f"kubectl rollout restart deployment/{deployment_name}{_namespace_flag(namespace)}"


def rollout_undo(deployment_name: str, namespace: str = "default") -> str:
    return f"kubectl rollout undo deployment/{deployment_name}{_namespace_flag(namespace)}"


def rollout_history(deployment_name: str, namespace: str = "default") -> str:
    return f"kubectl rollout history deployment/{deployment_name}{_namespace_flag(namespace)}"


# --- Config & secrets ---


def get_configmaps(namespace: str = "default") -> str:
    return k8s_resource_status("configmaps", namespace)


def get_secrets(namespace: str = "default") -> str:
    return k8s_resource_status("secrets", namespace)


# --- Storage ---


def get_persistent_volumes() -> str:
    return "kubectl get pv"


def get_persistent_volume_claims(namespace: str = "default", all_namespaces: bool = False) -> str:
    return k8s_resource_status("pvc", namespace, all_namespaces)


# --- Jobs & cron ---


def get_jobs(namespace: str = "default") -> str:
    return k8s_resource_status("jobs", namespace)


def get_cronjobs(namespace: str = "default") -> str:
    return k8s_resource_status("cronjobs", namespace)


# --- RBAC & policy ---


def get_roles(namespace: str = "default") -> str:
    return k8s_resource_status("roles", namespace)


def get_rolebindings(namespace: str = "default") -> str:
    return k8s_resource_status("rolebindings", namespace)


def get_network_policies(namespace: str = "default") -> str:
    return k8s_resource_status("networkpolicies", namespace)


# --- Create / delete ---


def create_namespace(namespace: str) -> str:
    return f"kubectl create namespace {namespace}"


def create_pod(pod_name: str, image: str, namespace: str = "default") -> str:
    return f"kubectl run {pod_name} --image={image}{_namespace_flag(namespace)}"


def create_deployment(
    deployment_name: str,
    image: str,
    replicas: int = 1,
    namespace: str = "default",
) -> str:
    return (
        f"kubectl create deployment {deployment_name} "
        f"--image={image} --replicas={replicas}{_namespace_flag(namespace)}"
    )


def expose_service(
    resource_name: str,
    port: int,
    target_port: int = 0,
    resource_type: str = "deployment",
    namespace: str = "default",
) -> str:
    tp = f" --target-port={target_port}" if target_port else ""
    return (
        f"kubectl expose {resource_type} {resource_name} "
        f"--port={port}{tp}{_namespace_flag(namespace)}"
    )


def delete_resource(
    resource_type: str,
    name: str,
    namespace: str = "default",
    force: bool = False,
) -> str:
    f = " --force --grace-period=0" if force else ""
    return f"kubectl delete {resource_type} {name}{_namespace_flag(namespace)}{f}"


def delete_pod(pod_name: str, namespace: str = "default", force: bool = False) -> str:
    return delete_resource("pod", pod_name, namespace, force)


# --- Node operations ---


def cordon_node(node_name: str) -> str:
    return f"kubectl cordon {node_name}"


def uncordon_node(node_name: str) -> str:
    return f"kubectl uncordon {node_name}"


# --- Labels & annotations ---


def label_resource(
    resource_type: str,
    name: str,
    labels: str,
    namespace: str = "default",
    overwrite: bool = False,
) -> str:
    ow = " --overwrite" if overwrite else ""
    return f"kubectl label {resource_type} {name}{_namespace_flag(namespace)} {labels}{ow}"


def annotate_resource(
    resource_type: str,
    name: str,
    annotations: str,
    namespace: str = "default",
    overwrite: bool = False,
) -> str:
    ow = " --overwrite" if overwrite else ""
    return f"kubectl annotate {resource_type} {name}{_namespace_flag(namespace)} {annotations}{ow}"
