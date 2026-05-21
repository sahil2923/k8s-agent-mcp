from dotenv import load_dotenv

load_dotenv()

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from instructions_loader import (
    CATEGORY_ORDER,
    DEBUG_POD_WORKFLOW,
    DEBUG_SERVICE_WORKFLOW,
    INSTRUCTIONS,
)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp/execute")
SESSION_ID = os.getenv("MCP_SESSION_ID", "vscode-session")

EXIT_COMMANDS = {"exit", "quit", "q", "bye"}
HELP_COMMANDS = {"help", "?", "commands"}

# Map common LLM alias names to canonical instruction names
INSTRUCTION_ALIASES = {
    "list_pods": "k8s_resource_status",
    "get_pods": "k8s_resource_status",
    "list_services": "k8s_resource_status",
    "get_logs": "get_pod_logs",
    "pod_logs": "get_pod_logs",
    "logs": "get_pod_logs",
    "describe_svc": "describe_service",
    "describe_service": "describe_service",
    "describe_deploy": "describe_deployment",
    "delete": "delete_resource",
}

PARAM_ALIASES = {
    "pod_name": ("name", "pod"),
    "service_name": ("service", "name", "svc"),
    "deployment_name": ("deployment", "name", "deploy"),
    "resource_type": ("type", "kind"),
    "namespace": ("ns",),
    "image": ("container_image",),
    "tail_lines": ("tail", "lines"),
}


def _required_hint(name: str) -> str:
    r = INSTRUCTIONS[name]["required"]
    return f" (requires: {', '.join(r)})" if r else ""


def build_prompt(message: str) -> str:
    catalog_lines = []
    for category in CATEGORY_ORDER:
        items = [
            (name, spec["summary"])
            for name, spec in INSTRUCTIONS.items()
            if spec["category"] == category
        ]
        if not items:
            continue
        catalog_lines.append(f"\n## {category.upper()}")
        for name, summary in sorted(items):
            catalog_lines.append(f"- {name}{_required_hint(name)}: {summary}")

    examples = [
        INSTRUCTIONS["k8s_resource_status"]["example"],
        INSTRUCTIONS["describe_pod"]["example"],
        INSTRUCTIONS["get_pod_logs"]["example"],
        INSTRUCTIONS["describe_service"]["example"],
        INSTRUCTIONS["scale_deployment"]["example"],
        [
            INSTRUCTIONS["create_namespace"]["example"],
            INSTRUCTIONS["create_pod"]["example"],
        ],
    ]

    return f"""You are a senior DevOps/SRE assistant that converts natural language into kubectl commands via JSON.

Return ONLY valid JSON — either one object or an ARRAY of objects:
{{"instruction": "<name>", "params": {{...}}}}

{len(INSTRUCTIONS)} supported instructions (by category):
{"".join(catalog_lines)}

RULES:
1. List ALL resources → k8s_resource_status with resource_type (pods|services|deployments|ingress|configmaps|secrets|nodes|...)
2. ONE named resource → get_resource, describe_*, or get_pod/get_service/get_deployment
3. Never use get_pod for "all pods" — use k8s_resource_status
4. Debug/troubleshoot a failing POD → return ARRAY (in order):
   get_pod → describe_pod → get_pod_events → get_pod_logs (tail_lines=200, previous=true if crash)
5. Debug a SERVICE → ARRAY: get_service → describe_service → get_endpoints → get_events
6. Rollout issues → rollout_status, rollout_history, rollout_undo, rollout_restart
7. Multi-step setup (namespace + pod) → JSON ARRAY, namespace first
8. namespace defaults to "default"; use all_namespaces:true for cluster-wide lists
9. resource_type uses kubectl plural names: pods, services, deployments, ingresses, configmaps

Example outputs:
{json.dumps(examples[0])}
{json.dumps(examples[3])}

Debug pod example:
{json.dumps(DEBUG_POD_WORKFLOW)}

Debug service example:
{json.dumps(DEBUG_SERVICE_WORKFLOW)}

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


def try_workflow_expand(message: str) -> Optional[List[dict]]:
    """Deterministic shortcuts for common debug phrases."""
    lower = message.lower()

    pod_match = re.search(
        r"debug(?:ging)?\s+(?:the\s+)?pod\s+['\"]?([\w.-]+)['\"]?"
        r"(?:\s+in\s+(?:the\s+)?['\"]?([\w.-]+)['\"]?\s*namespace)?",
        lower,
    )
    if pod_match:
        pod_name = pod_match.group(1)
        namespace = pod_match.group(2) or "default"
        return _fill_workflow(DEBUG_POD_WORKFLOW, pod_name=pod_name, namespace=namespace)

    svc_match = re.search(
        r"debug(?:ging)?\s+(?:the\s+)?(?:service|svc)\s+['\"]?([\w.-]+)['\"]?"
        r"(?:\s+in\s+(?:the\s+)?['\"]?([\w.-]+)['\"]?\s*namespace)?",
        lower,
    )
    if svc_match:
        service_name = svc_match.group(1)
        namespace = svc_match.group(2) or "default"
        return _fill_workflow(
            DEBUG_SERVICE_WORKFLOW,
            service_name=service_name,
            namespace=namespace,
        )

    return None


def _fill_workflow(template: List[dict], **values: str) -> List[dict]:
    out = []
    for step in template:
        blob = json.dumps(step)
        for key, val in values.items():
            blob = blob.replace("{" + key + "}", val)
        out.append(json.loads(blob))
    return out


async def parse_nl_to_command(message: str) -> Optional[List[dict]]:
    workflow = try_workflow_expand(message)
    if workflow:
        return normalize_commands(workflow)

    client, model = _llm_client()
    prompt = build_prompt(message)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Kubernetes operator. "
                        "Output only JSON for kubectl operations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=800,
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
        return normalize_commands(parsed)
    except json.JSONDecodeError:
        print("⚠️ Failed to parse JSON from model response:")
        print(raw_output)
        return None


def _normalize_params(params: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    normalized = dict(params)
    for canonical, aliases in PARAM_ALIASES.items():
        if canonical in normalized:
            continue
        for alias in aliases:
            if alias in normalized:
                normalized[canonical] = normalized.pop(alias)
                break

    if allowed:
        normalized = {
            k: v for k, v in normalized.items()
            if k in allowed and v not in (None, "")
        }
    return normalized


def normalize_commands(parsed) -> Optional[List[dict]]:
    if isinstance(parsed, dict):
        commands = [parsed]
    elif isinstance(parsed, list):
        commands = parsed
    else:
        return None

    normalized = []
    for cmd in commands:
        one = normalize_command(cmd)
        if one:
            normalized.append(one)
    return normalized or None


def normalize_command(command: dict) -> Optional[dict]:
    if not isinstance(command, dict):
        return None

    instruction = command.get("instruction")
    if instruction in INSTRUCTION_ALIASES:
        instruction = INSTRUCTION_ALIASES[instruction]

    if instruction not in INSTRUCTIONS:
        print(f"⚠️ Unknown instruction: {instruction}")
        return None

    spec = INSTRUCTIONS[instruction]
    params = _normalize_params(dict(command.get("params") or {}), spec["params"])

    # get_pod misused for listing
    if instruction == "get_pod" and "resource_type" in command.get("params", {}):
        instruction = "k8s_resource_status"
        spec = INSTRUCTIONS[instruction]
        params = _normalize_params(command.get("params", {}), spec["params"])

    for key in spec["required"]:
        if key not in params or params[key] in (None, ""):
            print(f"⚠️ {instruction} requires '{key}'.")
            return None

    if instruction == "k8s_resource_status":
        params.setdefault("resource_type", "pods")
        params.setdefault("namespace", "default")

    if instruction in ("get_pod", "describe_pod", "get_pod_logs", "get_pod_yaml", "get_pod_events"):
        params.setdefault("namespace", "default")

    if instruction in ("describe_service", "get_service", "get_endpoints"):
        params.setdefault("namespace", "default")

    if instruction in ("describe_deployment", "get_deployment", "scale_deployment", "rollout_status",
                       "rollout_restart", "rollout_undo", "rollout_history"):
        params.setdefault("namespace", "default")

    if instruction == "create_pod":
        params.setdefault("namespace", "default")

    if instruction == "get_pod_logs":
        params.setdefault("tail_lines", "100")

    return {"instruction": instruction, "params": params}


def print_help():
    print(f"\n📚 {len(INSTRUCTIONS)} kubectl operations available:\n")
    for category in CATEGORY_ORDER:
        items = [
            (n, INSTRUCTIONS[n]["summary"])
            for n, s in INSTRUCTIONS.items()
            if s["category"] == category
        ]
        if not items:
            continue
        print(f"  [{category}]")
        for name, summary in sorted(items):
            print(f"    • {name}: {summary}")
    print("\n  Workflows: say 'debug pod <name>' or 'debug service <name>' for multi-step troubleshooting.")
    print(f"  Exit: {', '.join(sorted(EXIT_COMMANDS))}\n")


async def call_mcp_server(command_json: dict):
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            MCP_SERVER_URL,
            json=command_json,
            params={"session_id": SESSION_ID},
        )
        if response.status_code == 200:
            return response.json()
        print(f"❌ MCP Server Error: {response.text}")
        return None


async def handle_command(user_input: str) -> None:
    commands = await parse_nl_to_command(user_input)
    if not commands:
        print("❌ Failed to parse natural language.")
        return

    print(f"\n✅ Parsed command(s):\n{json.dumps(commands, indent=2)}")

    for i, command_json in enumerate(commands, start=1):
        if len(commands) > 1:
            print(f"\n--- Step {i}/{len(commands)} ---")
        result = await call_mcp_server(command_json)
        if result:
            print("\n📦 MCP Output:")
            print(f"Command: {result['command']}")
            output = result["output"]
            print(f"Output:\n{output if output else '(empty)'}")


async def main():
    print("K8s DevOps Agent — natural language → kubectl")
    print(f"  {len(INSTRUCTIONS)} operations | type 'help' for commands | Ctrl+C to stop\n")

    while True:
        try:
            user_input = input("🧠 Enter your K8s command (natural language): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in EXIT_COMMANDS:
            print("👋 Goodbye!")
            break

        if user_input.lower() in HELP_COMMANDS:
            print_help()
            continue

        await handle_command(user_input)
        print()


if __name__ == "__main__":
    asyncio.run(main())
