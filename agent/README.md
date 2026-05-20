# AGENT

## Local development - required Python 3.11+

1. Create & activate venv:
❯ python3 -m venv .venv
❯ source .venv/bin/activate

2. Configure API key

Copy the example env file and add your key:

```bash
cp .env.example .env
```

**OpenRouter:** set `OPENROUTER_API_KEY` (keys start with `sk-or-v1-`). The agent auto-uses `https://openrouter.ai/api/v1`.

**OpenAI:** set `OPENAI_API_KEY` instead (no base URL override needed).

Optional: `OPENROUTER_MODEL=openai/gpt-4o-mini` (default for OpenRouter).

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Run agent (interactive REPL — keeps running until you type `exit` or Ctrl+C)

```bash
python3 agent.py
```

Type **`help`** inside the agent to see all 54+ kubectl operations.

**Example prompts:**

- `list all pods in kube-system`
- `describe deployment api in prod`
- `debug pod crashloop-api in production`
- `debug service frontend in default`
- `rollout status for deployment api in prod`
- `scale deployment api to 5 replicas in prod`
- `get events in default namespace`
- `top pods in kube-system`


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