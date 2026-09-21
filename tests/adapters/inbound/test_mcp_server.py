"""MCP tools end to end — tool -> registry -> use case -> port -> storage ->
response — with `FakeBrokerPort` registered under its own name, so nothing
touches Kite."""

import asyncio
from collections.abc import Iterator
from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Tool

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.ports.models import Exchange, InstrumentType, Interval
from tests.fixtures.fake_broker import FAKE_LAST_PRICE, FakeBrokerPort


@pytest.fixture(autouse=True)
def _fake_broker_registered() -> Iterator[None]:
    registry.register("fake", FakeBrokerPort)
    yield
    del registry.BROKER_REGISTRY["fake"]


def _tools() -> list[Tool]:
    return asyncio.run(mcp_server.mcp.list_tools())


def test_get_quote_after_sync_returns_resolved_quote() -> None:
    assert mcp_server.sync_instruments(broker="fake").instrument_count == 1

    result = mcp_server.get_quote(broker="fake", symbol="RELIANCE", exchange=Exchange.NSE)

    assert result.symbol == "RELIANCE"
    assert result.last_price == FAKE_LAST_PRICE
    assert result.as_of.utcoffset() is not None


def test_get_historical_bars_returns_exchange_local_times_and_explains_truncation() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.get_historical_bars(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=Interval.DAY,
        start_date=date(2026, 9, 18),
        end_date=date(2026, 9, 19),
        max_bars=1,
    )

    assert result.total_bars == 2
    assert [bar.timestamp.isoformat() for bar in result.bars] == ["2026-09-19T00:00:00+05:30"]
    assert result.note is not None and "max_bars" in result.note


def test_search_instruments_finds_synced_symbol() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.search_instruments(query="relian", instrument_type=InstrumentType.EQ)

    assert [instrument.symbol for instrument in result.instruments] == ["RELIANCE"]
    assert result.truncated is False


def test_agent_fixable_errors_reach_the_agent_with_their_message() -> None:
    with pytest.raises(ToolError, match="sync_instruments"):
        mcp_server.get_quote(broker="fake", symbol="RELIANCE", exchange=Exchange.NSE)

    with pytest.raises(ToolError, match="no broker adapter registered"):
        mcp_server.get_quote(broker="nonexistent", symbol="RELIANCE", exchange=Exchange.NSE)


def test_every_tool_is_fully_described_for_agents() -> None:
    """Conventions from ADR 8 in docs/adr, enforced for every tool, current and future."""
    for tool in _tools():
        assert tool.title, tool.name
        assert tool.description, tool.name
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is not None, tool.name
        assert tool.annotations.open_world_hint is not None, tool.name
        if not tool.annotations.read_only_hint:
            assert tool.annotations.destructive_hint is not None, tool.name
            assert tool.annotations.idempotent_hint is not None, tool.name
        assert tool.output_schema is not None, tool.name
        for name, schema in tool.input_schema["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"


def test_server_tells_the_agent_the_workflow() -> None:
    assert "sync_instruments" in (mcp_server.mcp.instructions or "")
