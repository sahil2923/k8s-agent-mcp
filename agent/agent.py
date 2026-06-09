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
    DEBUG_DEPLOYMENT_WORKFLOW,
    DEBUG_POD_WORKFLOW,
    DEBUG_SERVICE_WORKFLOW,
    DESTRUCTIVE_INSTRUCTIONS,
    INSTRUCTIONS,
)

MCP_BASE_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080").rstrip("/")
MCP_EXECUTE_URL = (
    MCP_BASE_URL
    if MCP_BASE_URL.endswith("/mcp/execute")
    else f"{MCP_BASE_URL}/mcp/execute"
)
MCP_BATCH_URL = MCP_EXECUTE_URL.replace("/mcp/execute", "/mcp/execute/batch")
MCP_HEALTH_URL = MCP_EXECUTE_URL.replace("/mcp/execute", "/health")
SESSION_ID = os.getenv("MCP_SESSION_ID", "vscode-session")
DRY_RUN_DEFAULT = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
REQUIRE_DESTRUCTIVE_CONFIRM = os.getenv(
    "REQUIRE_DESTRUCTIVE_CONFIRM", "true"
).lower() not in ("0", "false", "no")

EXIT_COMMANDS = {"exit", "quit", "q", "bye"}
HELP_COMMANDS = {"help", "?", "commands"}
DRY_RUN_PREFIXES = ("dry:", "dry-run:", "preview:")

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

Debug deployment example:
{json.dumps(DEBUG_DEPLOYMENT_WORKFLOW)}

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

    deploy_match = re.search(
        r"debug(?:ging)?\s+(?:the\s+)?(?:deployment|deploy)\s+['\"]?([\w.-]+)['\"]?"
        r"(?:\s+in\s+(?:the\s+)?['\"]?([\w.-]+)['\"]?\s*namespace)?",
        lower,
    )
    if deploy_match:
        deployment_name = deploy_match.group(1)
        namespace = deploy_match.group(2) or "default"
        return _fill_workflow(
            DEBUG_DEPLOYMENT_WORKFLOW,
            deployment_name=deployment_name,
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
    print("\n  Workflows: 'debug pod <name>', 'debug service <name>', 'debug deployment <name>'")
    print("  Preview: prefix with 'dry:' to show kubectl without running (e.g. dry: delete pod nginx)")
    print(f"  Exit: {', '.join(sorted(EXIT_COMMANDS))}\n")


def _parse_dry_run(user_input: str) -> tuple[str, bool]:
    lower = user_input.lower()
    for prefix in DRY_RUN_PREFIXES:
        if lower.startswith(prefix):
            return user_input[len(prefix):].strip(), True
    return user_input, DRY_RUN_DEFAULT


def _format_mcp_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            if "error" in detail:
                return str(detail["error"])
            return json.dumps(detail, indent=2)
        return str(detail)
    except json.JSONDecodeError:
        return response.text


async def check_mcp_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(MCP_HEALTH_URL)
            if response.status_code != 200:
                print(f"⚠️ MCP health check failed ({response.status_code})")
                return False
            data = response.json()
            status = data.get("status", "unknown")
            print(f"✅ MCP server {status} | {data.get('instructions', '?')} instructions")
            if not data.get("cluster_reachable"):
                print("⚠️ kubectl client OK but cluster not reachable — check minikube/kubectl context")
            return status in ("healthy", "degraded")
    except httpx.RequestError as e:
        print(f"❌ Cannot reach MCP server at {MCP_HEALTH_URL}: {e}")
        print("   Start it with: cd mcp_server && poetry run uvicorn k8s_mcp_server.server:app --port 8080")
        return False


def _needs_confirmation(commands: List[dict]) -> bool:
    if not REQUIRE_DESTRUCTIVE_CONFIRM:
        return False
    return any(cmd["instruction"] in DESTRUCTIVE_INSTRUCTIONS for cmd in commands)


def _confirm_destructive(commands: List[dict]) -> bool:
    destructive = [c for c in commands if c["instruction"] in DESTRUCTIVE_INSTRUCTIONS]
    print("\n⚠️  Destructive operation(s) detected:")
    for cmd in destructive:
        print(f"   • {cmd['instruction']}: {json.dumps(cmd['params'])}")
    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


async def call_mcp_server(command_json: dict, dry_run: bool = False):
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            MCP_EXECUTE_URL,
            json=command_json,
            params={"session_id": SESSION_ID, "dry_run": dry_run},
        )
        if response.status_code == 200:
            return response.json()
        print(f"❌ MCP Server Error: {_format_mcp_error(response)}")
        return None


async def call_mcp_batch(commands: List[dict], dry_run: bool = False):
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            MCP_BATCH_URL,
            json={"commands": commands},
            params={"session_id": SESSION_ID, "dry_run": dry_run},
        )
        if response.status_code == 200:
            return response.json()
        print(f"❌ MCP Batch Error: {_format_mcp_error(response)}")
        return None


def _print_result(result: dict) -> None:
    print("\n📦 MCP Output:")
    if result.get("dry_run"):
        print("(dry-run — not executed)")
    print(f"Command: {result['command']}")
    output = result.get("output", "")
    print(f"Output:\n{output if output else '(empty)'}")


async def handle_command(user_input: str, dry_run: bool = False) -> None:
    commands = await parse_nl_to_command(user_input)
    if not commands:
        print("❌ Failed to parse natural language.")
        return

    if dry_run:
        print("\n🔍 Dry-run mode — commands will be shown but not executed")

    print(f"\n✅ Parsed command(s):\n{json.dumps(commands, indent=2)}")

    if not dry_run and _needs_confirmation(commands):
        if not _confirm_destructive(commands):
            print("❌ Cancelled.")
            return

    if len(commands) > 1:
        batch = await call_mcp_batch(commands, dry_run=dry_run)
        if not batch:
            return
        for result in batch.get("results", []):
            step = result.get("step", "?")
            print(f"\n--- Step {step}/{batch.get('steps', '?')} ---")
            _print_result(result)
        return

    result = await call_mcp_server(commands[0], dry_run=dry_run)
    if result:
        _print_result(result)


async def main():
    print("K8s DevOps Agent — natural language → kubectl")
    print(f"  {len(INSTRUCTIONS)} operations | type 'help' for commands | Ctrl+C to stop")
    if DRY_RUN_DEFAULT:
        print("  DRY_RUN=true — all commands preview-only until you unset it")
    await check_mcp_health()
    print()

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

        message, dry_run = _parse_dry_run(user_input)
        if not message:
            continue

        await handle_command(message, dry_run=dry_run)
        print()


if __name__ == "__main__":
    asyncio.run(main())
