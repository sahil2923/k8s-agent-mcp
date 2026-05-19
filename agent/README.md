# AGENT

## Local development - required Python 3.11+

1. Create & activate venv:
❯ python3 -m venv .venv
❯ source .venv/bin/activate

2. Install dependencies
❯ pip install -r requirements.txt

3. Run agent
❯ python3 agent.py


# Output
❯ python3 agent.py
🧠 Enter your K8s command (natural language): show me all the running pods from default cluster

✅ Parsed command:
{
  "instruction": "k8s_resource_status",
  "params": {
    "resource_type": "pods",
    "namespace": "default"
  }
}

📦 MCP Output:
Command: kubectl get pods -n default
Output:
NAME    READY   STATUS      RESTARTS   AGE
nginx   0/1     Completed   0          3d16h