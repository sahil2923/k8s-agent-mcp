import asyncio
import inspect

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional

from k8s_mcp_server import prompts
from k8s_mcp_server.instructions_catalog import INSTRUCTIONS

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


@app.get("/")
def root():
    return {
        "message": "K8s MCP Server is running",
        "instructions": len(PROMPT_FUNCTIONS),
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
        }
        for name, spec in INSTRUCTIONS.items()
    }


@app.post("/mcp/execute")
async def execute_mcp(req: MCPRequest, session_id: Optional[str] = Query(None)):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

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

    try:
        cmd = PROMPT_FUNCTIONS[req.instruction](**params)
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameters for {req.instruction}: {e}",
        )

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err = stderr.decode().strip() or stdout.decode().strip()
        raise HTTPException(status_code=500, detail=err)

    return {
        "session_id": session_id,
        "instruction": req.instruction,
        "command": cmd,
        "output": stdout.decode().strip(),
    }
