from dotenv import load_dotenv

load_dotenv()

import asyncio
import json
import os
from typing import Optional

import httpx
from openai import AsyncOpenAI

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp/execute")
SESSION_ID = os.getenv("MCP_SESSION_ID", "vscode-session")

INSTRUCTIONS = {
    "k8s_resource_status": {
        "params": ["resource_type", "namespace"],
        "use_when": "list/show/get ALL resources of a type (pods, services, deployments, etc.)",
        "example": {
            "instruction": "k8s_resource_status",
            "params": {"resource_type": "pods", "namespace": "default"},
        },
    },
    "get_pod": {
        "params": ["pod_name", "namespace"],
        "use_when": "get ONE specific pod by name",
        "example": {
            "instruction": "get_pod",
            "params": {"pod_name": "nginx", "namespace": "default"},
        },
    },
    "describe_pod": {
        "params": ["pod_name", "namespace"],
        "use_when": "describe/describe details of ONE specific pod",
        "example": {
            "instruction": "describe_pod",
            "params": {"pod_name": "nginx", "namespace": "default"},
        },
    },
    "get_pod_logs": {
        "params": ["pod_name", "namespace", "container"],
        "use_when": "logs from ONE specific pod (container optional)",
        "example": {
            "instruction": "get_pod_logs",
            "params": {"pod_name": "nginx", "namespace": "default"},
        },
    },
}

def build_prompt(message: str) -> str:
    examples = "\n".join(
        json.dumps(spec["example"]) for spec in INSTRUCTIONS.values()
    )
    return f"""
You convert Kubernetes natural language into JSON for an MCP server.

Return ONLY valid JSON: {{"instruction": "...", "params": {{...}}}}

Instructions (pick exactly one):

1. k8s_resource_status — list ALL resources of a type
   params: resource_type (pods|services|deployments|...), namespace (default if omitted)
   Use for: "show all pods", "list deployments in kube-system", "get services"

2. get_pod — get ONE pod by name
   params: pod_name (required), namespace
   Use for: "get pod nginx", "show pod redis-0"

3. describe_pod — describe ONE pod by name
   params: pod_name (required), namespace
   Use for: "describe pod api-server"

4. get_pod_logs — logs for ONE pod
   params: pod_name (required), namespace, container (optional)
   Use for: "logs for pod nginx", "tail logs api-server in prod"

Rules:
- "all pods", "running pods", "pods in namespace" → k8s_resource_status (NOT get_pod)
- get_pod/describe_pod/get_pod_logs require pod_name; never use resource_type with them
- namespace defaults to "default" when not specified

Examples:
{examples}

User message: {json.dumps(message)}
"""


def _llm_client() -> tuple[AsyncOpenAI, str]:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY or OPENAI_API_KEY in agent/.env"
        )

    base_url = os.getenv("OPENAI_API_BASE")
    if not base_url and (
        os.getenv("OPENROUTER_API_KEY") or api_key.startswith("sk-or-")
    ):
        base_url = "https://openrouter.ai/api/v1"

    model = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENAI_MODEL")
    if not model:
        model = "openai/gpt-4o-mini" if base_url and "openrouter" in base_url else "gpt-4o"

    extra_headers = {}
    if base_url and "openrouter" in base_url:
        extra_headers = {
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
            "X-Title": os.getenv("OPENROUTER_APP_NAME", "k8s-agent-mcp"),
        }

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=extra_headers or None,
    )
    return client, model


async def parse_nl_to_command(message: str) -> Optional[dict]:
    client, model = _llm_client()
    prompt = build_prompt(message)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150,
        )
    except Exception as e:
        print(f"❌ LLM request failed: {e}")
        return None

    raw_output = (response.choices[0].message.content or "").strip()

    if raw_output.startswith("```"):
        lines = [
            line for line in raw_output.splitlines()
            if not line.strip().startswith("```")
        ]
        raw_output = "\n".join(lines).strip()

    try:
        parsed = json.loads(raw_output)
        return normalize_command(parsed)
    except json.JSONDecodeError:
        print("⚠️ Failed to parse JSON from model response:")
        print(raw_output)
        return None


def normalize_command(command: dict) -> Optional[dict]:
    """Fix common LLM mistakes before calling the MCP server."""
    if not isinstance(command, dict):
        return None

    instruction = command.get("instruction")
    params = dict(command.get("params") or {})

    # List-all phrasing wrongly mapped to get_pod with resource_type
    if instruction == "get_pod" and "resource_type" in params and "pod_name" not in params:
        instruction = "k8s_resource_status"
        params.setdefault("namespace", "default")

    allowed = INSTRUCTIONS.get(instruction, {}).get("params", [])
    if allowed:
        params = {k: v for k, v in params.items() if k in allowed and v not in (None, "")}

    if instruction in ("get_pod", "describe_pod", "get_pod_logs") and "pod_name" not in params:
        print(f"⚠️ {instruction} requires pod_name; could not infer from request.")
        return None

    if instruction == "k8s_resource_status":
        params.setdefault("resource_type", "pods")
        params.setdefault("namespace", "default")

    return {"instruction": instruction, "params": params}


async def call_mcp_server(command_json: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            MCP_SERVER_URL,
            json=command_json,
            params={"session_id": SESSION_ID},
        )
        if response.status_code == 200:
            return response.json()
        print(f"❌ MCP Server Error: {response.text}")
        return None


async def main():
    user_input = input("🧠 Enter your K8s command (natural language): ")

    command_json = await parse_nl_to_command(user_input)
    if not command_json:
        print("❌ Failed to parse natural language.")
        return

    print(f"\n✅ Parsed command:\n{json.dumps(command_json, indent=2)}")

    result = await call_mcp_server(command_json)
    if result:
        print("\n📦 MCP Output:")
        print(f"Command: {result['command']}")
        print(f"Output:\n{result['output']}")


if __name__ == "__main__":
    asyncio.run(main())
