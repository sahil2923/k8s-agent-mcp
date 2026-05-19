# K8s MCP Server

## Local development

1. Create & activate venv:
❯ python3 -m venv .venv
❯ source .venv/bin/activate

2. Install dependencies
❯ poetry install

# If poetry is not installed, install it using brew install poetry

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
❯ brew insatll kubectl

Once Minikube is started you should be able to execute kubectl commands

# Test if MCP is able to reach Minikube cluster using curl

❯ curl -X POST "http://localhost:8080/mcp/execute?session_id=my-session-id" \
  -H "Content-Type: application/json" \
  -d '{
    "instruction": "k8s_resource_status",
    "params": {
      "resource_type": "pods",
      "namespace": "default"
    }
  }'
