from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from engine.tools.fetch_bars import fetch_bars
from ingest.core.models import Bar


def _bar(day: int, close: float) -> Bar:
    return Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="kite",
    )


@pytest.mark.asyncio
async def test_fetch_bars_returns_serialized_bars_and_summary() -> None:
    bars = [_bar(1, 100.0), _bar(2, 105.0)]
    with (
        patch(
            "engine.tools.fetch_bars.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.fetch_bars.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
    ):
        result = await fetch_bars(symbol="RELIANCE", interval="1d", days=30, provider="kite")

    assert result["provider"] == "kite"
    assert result["symbol"] == "RELIANCE"
    assert result["bar_count"] == 2
    assert result["bars"][0]["close"] == 100.0
    assert result["first_close"] == 100.0
    assert result["last_close"] == 105.0


@pytest.mark.asyncio
async def test_fetch_bars_defaults_provider_to_none() -> None:
    bars = [_bar(1, 100.0)]
    with (
        patch(
            "engine.tools.fetch_bars.connect_engine", new=AsyncMock(return_value=("kite", object()))
        ) as mock_connect,
        patch("engine.tools.fetch_bars.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
    ):
        await fetch_bars(symbol="RELIANCE")

    mock_connect.assert_called_once_with(None)
