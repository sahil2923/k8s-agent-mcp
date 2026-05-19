# FLOW
[In Terminal / VSCode] 👈
        │
        ▼
[Natural language input] ---> [Python Agent]
                               │
                               ▼
                    [OpenAI API - GPT model]
                               │
                               ▼
         (JSON command e.g. {"instruction": ..., "params": {...}})
                               │
                               ▼
              [Your Python agent HTTP POSTs to:]
              http://localhost:8080/mcp/execute
                               │
                               ▼
               [MCP Server executes kubectl command]
                               │
                               ▼
               [Returns stdout from Minikube]
                               │
                               ▼
                   [Printed in your Terminal 💡]


# Follow respective README.md files for running agent & mcp_server 


# Note: 
Code was developed and tested on Mac, Apple M1. So there might be some adjustments needed considering the OS you are running. Rest everything should work.


# Input 
🧠 Enter your K8s command (natural language): show me all the running pods from default cluster

# Output
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