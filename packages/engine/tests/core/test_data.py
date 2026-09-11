from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from engine.core.data import connect_engine, fetch_symbol_bars, resolve_provider
from engine.core.exceptions import (
    NotConnectedError,
    ProviderRateLimitedError,
    SessionExpiredError,
)
from ingest.core import exceptions as ingest_exc
from ingest.core.models import Bar


def test_resolve_provider_returns_stored_credentials_for_explicit_provider() -> None:
    with patch("engine.core.data.load_credentials", return_value={"api_key": "k1"}):
        assert resolve_provider("kite") == ("kite", {"api_key": "k1"})


def test_resolve_provider_raises_when_explicit_provider_has_no_stored_session() -> None:
    with (
        patch("engine.core.data.load_credentials", return_value=None),
        pytest.raises(NotConnectedError, match="groww"),
    ):
        resolve_provider("groww")


def test_resolve_provider_falls_back_to_most_recent_when_no_explicit_provider() -> None:
    with patch("engine.core.data.load_most_recent", return_value=("kite", {"api_key": "k1"})):
        assert resolve_provider(None) == ("kite", {"api_key": "k1"})


def test_resolve_provider_raises_when_nothing_connected() -> None:
    with (
        patch("engine.core.data.load_most_recent", return_value=None),
        pytest.raises(NotConnectedError, match="not connected|no adapter"),
    ):
        resolve_provider(None)


@pytest.mark.asyncio
async def test_connect_engine_translates_auth_expired_to_session_expired() -> None:
    mock_adapter = Mock()
    mock_adapter.connect = AsyncMock(side_effect=ingest_exc.AuthExpiredError("expired"))

    with (
        patch("engine.core.data.resolve_provider", return_value=("kite", {"api_key": "k"})),
        patch("engine.core.data.AdapterFactory") as mock_factory,
    ):
        mock_factory.create.return_value = mock_adapter
        with pytest.raises(SessionExpiredError, match="kite"):
            await connect_engine("kite")


@pytest.mark.asyncio
async def test_connect_engine_translates_rate_limit_error() -> None:
    mock_adapter = Mock()
    mock_adapter.connect = AsyncMock(side_effect=ingest_exc.RateLimitError("too many requests"))

    with (
        patch("engine.core.data.resolve_provider", return_value=("kite", {"api_key": "k"})),
        patch("engine.core.data.AdapterFactory") as mock_factory,
    ):
        mock_factory.create.return_value = mock_adapter
        with pytest.raises(ProviderRateLimitedError, match="rate-limited"):
            await connect_engine("kite")


def _bar(day: int) -> Bar:
    return Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, day, tzinfo=UTC),
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        volume=1000,
        provider="kite",
    )


@pytest.mark.asyncio
async def test_fetch_symbol_bars_returns_bars_on_success() -> None:
    mock_engine = Mock()
    mock_engine.fetch_historical = AsyncMock(return_value=[_bar(1), _bar(2)])
    result = await fetch_symbol_bars(
        mock_engine,
        "kite",
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_fetch_symbol_bars_translates_auth_expired_to_session_expired() -> None:
    mock_engine = Mock()
    mock_engine.fetch_historical = AsyncMock(side_effect=ingest_exc.AuthExpiredError("expired"))
    with pytest.raises(SessionExpiredError, match="kite"):
        await fetch_symbol_bars(
            mock_engine,
            "kite",
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_fetch_symbol_bars_translates_rate_limit_error() -> None:
    mock_engine = Mock()
    mock_engine.fetch_historical = AsyncMock(side_effect=ingest_exc.RateLimitError("too many requests"))
    with pytest.raises(ProviderRateLimitedError, match="rate-limited"):
        await fetch_symbol_bars(
            mock_engine,
            "kite",
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_fetch_symbol_bars_raises_data_unavailable_when_no_bars() -> None:
    mock_engine = Mock()
    mock_engine.fetch_historical = AsyncMock(return_value=[])
    with pytest.raises(ingest_exc.DataUnavailableError, match="RELIANCE"):
        await fetch_symbol_bars(
            mock_engine,
            "kite",
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        )
