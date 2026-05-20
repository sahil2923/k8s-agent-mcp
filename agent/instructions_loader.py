"""Load shared instruction catalog from mcp_server package."""
import sys
from pathlib import Path

_MCP_SRC = Path(__file__).resolve().parents[1] / "mcp_server" / "src"
if str(_MCP_SRC) not in sys.path:
    sys.path.insert(0, str(_MCP_SRC))

from k8s_mcp_server.instructions_catalog import (  # noqa: E402
    CATEGORY_ORDER,
    DEBUG_POD_WORKFLOW,
    DEBUG_SERVICE_WORKFLOW,
    INSTRUCTIONS,
)
