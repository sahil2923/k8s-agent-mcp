# K8s MCP Server

## Local development

1. Create & activate venv:
❯ python3 -m venv .venv
❯ source .venv/bin/activate

2. Install dependencies

**Option A — pip (venv)**

```bash
pip install -r requirements.txt
```

**Option B — Poetry**

```bash
poetry install
```

# If poetry is not installed: brew install poetry

3. Activate your environment:
❯ source "$(poetry env info --path)/bin/activate"

Or use below,  If you added the shell plugin -
❯ poetry shell

4. Run Locally with Poetry 
# Execute this in /dir where pyproject.toml exists
❯ PYTHONPATH=src poetry run uvicorn k8s_mcp_server.server:app --host 0.0.0.0 --port 8080 --reload

################################################################

# Install & start Minikube
Follow this guide for installation - https://minikube.sigs.k8s.io/docs/start/?arch=%2Fmacos%2Farm64%2Fstable%2Fbinary+download

❯ minikube start

# Install kubectl
❯ brew install kubectl

Once Minikube is started you should be able to execute kubectl commands

# Test if MCP is able to reach Minikube cluster using curl

❯ curl http://localhost:8080/health

❯ curl -X POST "http://localhost:8080/mcp/execute?session_id=my-session-id" \
  -H "Content-Type: application/json" \
  -d '{
    "instruction": "k8s_resource_status",
    "params": {
      "resource_type": "pods",
      "namespace": "default"
    }
  }'

# Dry-run (build command without executing):
❯ curl -X POST "http://localhost:8080/mcp/execute?session_id=my-session-id&dry_run=true" \
  -H "Content-Type: application/json" \
  -d '{"instruction": "delete_pod", "params": {"pod_name": "nginx", "namespace": "default"}}'

# Batch execute (debug workflows):
❯ curl -X POST "http://localhost:8080/mcp/execute/batch?session_id=my-session-id" \
  -H "Content-Type: application/json" \
  -d '{"commands": [
    {"instruction": "get_pod", "params": {"pod_name": "nginx", "namespace": "default"}},
    {"instruction": "describe_pod", "params": {"pod_name": "nginx", "namespace": "default"}}
  ]}'

## Troubleshooting

### `ImportError: cannot import name 'validate_core_schema' from 'pydantic_core'`

This means `pydantic` and `pydantic-core` were installed at incompatible versions (common with Python 3.14 + loose pins). Fix:

```bash
source venv/bin/activate   # or: source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

Recommended: use **Python 3.11–3.13** for this project (`python3.12 -m venv venv`).
