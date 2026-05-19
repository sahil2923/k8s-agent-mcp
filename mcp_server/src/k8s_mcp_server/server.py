import asyncio
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional

from k8s_mcp_server import prompts

app = FastAPI(title="K8s MCP Server")

# Map instruction names to prompt functions
PROMPT_FUNCTIONS = {
    "k8s_resource_status": prompts.k8s_resource_status,
    "describe_pod": prompts.describe_pod,
    "get_pod_logs": prompts.get_pod_logs,
    "get_pod": prompts.get_pod,
}

class MCPRequest(BaseModel):
    instruction: str
    params: Optional[Dict[str, Any]] = {}

@app.post("/mcp/execute")
async def execute_mcp(req: MCPRequest, session_id: Optional[str] = Query(None)):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    if req.instruction not in PROMPT_FUNCTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown instruction: {req.instruction}")

    try:
        # Generate the shell command string from prompt function
        cmd = PROMPT_FUNCTIONS[req.instruction](**req.params)
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters for instruction: {e}")

    # Execute the command asynchronously
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise HTTPException(status_code=500, detail=stderr.decode().strip())

    return {
        "session_id": session_id,
        "command": cmd,
        "output": stdout.decode().strip(),
    }

@app.get("/")
def root():
    return {"message": "K8s MCP Server is running"}
