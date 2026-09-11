"""Quant Engine MCP server - one process, every harness attaches to it.

Spawned as a stdio subprocess by the calling harness (Claude Code via
plugin/.mcp.json) at session start, killed on exit. Not a daemon - see
docs/superpowers/specs/2026-09-11-quant-engine-mcp-design.md's
Architecture section.

Codex support is still a later, separate slice - only Claude Code
(plugin/.mcp.json) registers this server today.

Run directly with: uv run python -m engine.server
"""

from mcp.server.fastmcp import FastMCP

from engine.core.constants import (
    SERVER_NAME,
    TOOL_CONNECT_ADAPTER,
    TOOL_EVALUATE_SIGNAL,
    TOOL_FETCH_BARS,
    TOOL_RUN_BACKTEST,
)
from engine.tools.connect_adapter import connect_adapter
from engine.tools.evaluate_signal import evaluate_signal
from engine.tools.fetch_bars import fetch_bars
from engine.tools.run_backtest import run_backtest

mcp = FastMCP(SERVER_NAME)

mcp.add_tool(evaluate_signal, name=TOOL_EVALUATE_SIGNAL)
mcp.add_tool(connect_adapter, name=TOOL_CONNECT_ADAPTER)
mcp.add_tool(fetch_bars, name=TOOL_FETCH_BARS)
mcp.add_tool(run_backtest, name=TOOL_RUN_BACKTEST)


def main() -> None:
    """Run the server over stdio - the entrypoint plugin/.mcp.json invokes."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
