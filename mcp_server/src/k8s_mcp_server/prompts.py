def k8s_resource_status(resource_type: str, namespace: str = "default") -> str:
    return f"kubectl get {resource_type} -n {namespace}"

def describe_pod(pod_name: str, namespace: str = "default") -> str:
    return f"kubectl describe pod {pod_name} -n {namespace}"

def get_pod_logs(pod_name: str, namespace: str = "default", container: str = "") -> str:
    container_part = f"-c {container}" if container else ""
    return f"kubectl logs {pod_name} -n {namespace} {container_part}"

def get_pod(pod_name: str, namespace: str = "default") -> str:
    return f"kubectl get pod {pod_name} -n {namespace}"
