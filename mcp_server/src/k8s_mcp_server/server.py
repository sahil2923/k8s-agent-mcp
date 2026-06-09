import asyncio
import inspect
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from k8s_mcp_server import prompts
from k8s_mcp_server.instructions_catalog import INSTRUCTIONS

logger = logging.getLogger("k8s_mcp_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CMD_TIMEOUT_SECONDS = int(os.getenv("K8S_CMD_TIMEOUT_SECONDS", "60"))

app = FastAPI(title="K8s MCP Server")


def _load_prompt_functions() -> dict:
    """Map instruction names to prompts.py functions."""
    functions = {}
    for name, func in inspect.getmembers(prompts, inspect.isfunction):
        if func.__module__ != prompts.__name__:
            continue
        if name.startswith("_"):
            continue
        functions[name] = func
    return functions


PROMPT_FUNCTIONS = _load_prompt_functions()

# Ensure catalog and prompts stay in sync
_missing = set(INSTRUCTIONS) - set(PROMPT_FUNCTIONS)
_extra = set(PROMPT_FUNCTIONS) - set(INSTRUCTIONS)
if _missing:
    raise RuntimeError(f"Catalog missing prompt functions: {_missing}")
if _extra:
    raise RuntimeError(f"Prompt functions not in catalog: {_extra}")


class MCPRequest(BaseModel):
    instruction: str
    params: Optional[Dict[str, Any]] = {}


class MCPBatchRequest(BaseModel):
    commands: List[MCPRequest]


def _validate_instruction(req: MCPRequest) -> tuple[dict, dict]:
    if req.instruction not in PROMPT_FUNCTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown instruction: {req.instruction}. GET /mcp/instructions for supported commands.",
        )

    spec = INSTRUCTIONS[req.instruction]
    params = dict(req.params or {})
    for key in spec["required"]:
        if key not in params or params[key] in (None, ""):
            raise HTTPException(
                status_code=400,
                detail=f"Missing required param '{key}' for {req.instruction}",
            )
    return spec, params


def _build_command(instruction: str, params: dict) -> str:
    try:
        cmd = PROMPT_FUNCTIONS[instruction](**params)
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameters for {instruction}: {e}",
        )

    if not cmd.strip().startswith("kubectl"):
        raise HTTPException(
            status_code=500,
            detail=f"Refusing to run non-kubectl command: {cmd}",
        )
    return cmd


async def _run_kubectl(cmd: str) -> tuple[str, str, int]:
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=CMD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(
            status_code=504,
            detail=f"Command timed out after {CMD_TIMEOUT_SECONDS}s: {cmd}",
        )

    return (
        stdout.decode().strip(),
        stderr.decode().strip(),
        process.returncode or 0,
    )


async def _execute_one(
    req: MCPRequest,
    session_id: str,
    dry_run: bool = False,
) -> dict:
    spec, params = _validate_instruction(req)
    cmd = _build_command(req.instruction, params)

    logger.info(
        "session=%s instruction=%s destructive=%s dry_run=%s",
        session_id,
        req.instruction,
        spec.get("destructive", False),
        dry_run,
    )

    if dry_run:
        return {
            "session_id": session_id,
            "instruction": req.instruction,
            "command": cmd,
            "output": "(dry-run — command not executed)",
            "dry_run": True,
            "destructive": spec.get("destructive", False),
        }

    stdout, stderr, returncode = await _run_kubectl(cmd)
    if returncode != 0:
        err = stderr or stdout
        raise HTTPException(status_code=500, detail=err)

    return {
        "session_id": session_id,
        "instruction": req.instruction,
        "command": cmd,
        "output": stdout,
        "destructive": spec.get("destructive", False),
    }


@app.get("/")
def root():
    return {
        "message": "K8s MCP Server is running",
        "instructions": len(PROMPT_FUNCTIONS),
        "timeout_seconds": CMD_TIMEOUT_SECONDS,
    }


@app.get("/health")
async def health():
    """Check kubectl availability and cluster connectivity."""
    started = time.monotonic()
    try:
        stdout, stderr, returncode = await _run_kubectl("kubectl version --client --output=yaml")
        client_ok = returncode == 0
        client_detail = stdout or stderr
    except HTTPException as e:
        client_ok = False
        client_detail = str(e.detail)

    cluster_ok = False
    cluster_detail = ""
    if client_ok:
        try:
            stdout, stderr, returncode = await _run_kubectl(
                "kubectl cluster-info --request-timeout=5s"
            )
            cluster_ok = returncode == 0
            cluster_detail = (stdout or stderr).splitlines()[0] if (stdout or stderr) else ""
        except HTTPException as e:
            cluster_detail = str(e.detail)

    status = "healthy" if client_ok and cluster_ok else "degraded" if client_ok else "unhealthy"
    return {
        "status": status,
        "kubectl_client": client_ok,
        "cluster_reachable": cluster_ok,
        "client_detail": client_detail[:200] if client_detail else "",
        "cluster_detail": cluster_detail,
        "instructions": len(PROMPT_FUNCTIONS),
        "latency_ms": round((time.monotonic() - started) * 1000),
    }


@app.get("/mcp/instructions")
def list_instructions():
    """List all supported kubectl instructions."""
    return {
        name: {
            "category": spec["category"],
            "summary": spec["summary"],
            "params": spec["params"],
            "required": spec["required"],
            "destructive": spec.get("destructive", False),
        }
        for name, spec in INSTRUCTIONS.items()
    }


@app.post("/mcp/execute")
async def execute_mcp(
    req: MCPRequest,
    session_id: Optional[str] = Query(None),
    dry_run: bool = Query(False, description="Build kubectl command without executing"),
):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return await _execute_one(req, session_id, dry_run=dry_run)


@app.post("/mcp/execute/batch")
async def execute_batch(
    req: MCPBatchRequest,
    session_id: Optional[str] = Query(None),
    dry_run: bool = Query(False),
    stop_on_error: bool = Query(True, description="Stop remaining steps if one fails"),
):
    """Run multiple instructions in sequence (e.g. debug workflows)."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if not req.commands:
        raise HTTPException(status_code=400, detail="commands list cannot be empty")

    results = []
    for i, command in enumerate(req.commands, start=1):
        try:
            result = await _execute_one(command, session_id, dry_run=dry_run)
            result["step"] = i
            results.append(result)
        except HTTPException as e:
            if stop_on_error:
                raise HTTPException(
                    status_code=e.status_code,
                    detail={
                        "error": e.detail,
                        "failed_step": i,
                        "completed_steps": len(results),
                        "partial_results": results,
                    },
                )
            results.append({
                "step": i,
                "instruction": command.instruction,
                "error": e.detail,
            })

    return {
        "session_id": session_id,
        "steps": len(results),
        "dry_run": dry_run,
        "results": results,
    }
