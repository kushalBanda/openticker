import pytest
from engine.server import mcp


@pytest.mark.asyncio
async def test_server_registers_all_four_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "evaluate_signal",
        "connect_adapter",
        "fetch_bars",
        "run_backtest",
    }


@pytest.mark.asyncio
async def test_every_tool_parameter_has_a_schema_description() -> None:
    """Every param must carry its own description in inputSchema, not just
    a docstring blob on the tool - that's what a model actually reads to
    fill in arguments correctly, per-field, not the whole description text.
    """
    tools = await mcp.list_tools()
    missing: list[str] = []
    for tool in tools:
        properties = tool.inputSchema.get("properties", {})
        for param_name, schema in properties.items():
            if not schema.get("description"):
                missing.append(f"{tool.name}.{param_name}")
    assert not missing, f"params with no schema description: {missing}"
