import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from growwapi import GrowwAPI
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPINotFoundException,
    GrowwAPIRateLimitException,
)
from ingest.adapters.groww.adapter import GrowwAdapter
from ingest.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)

_HISTORICAL_RESPONSE: dict[str, Any] = {
    "candles": [
        [1735718400, 100.0, 105.0, 99.0, 104.0, 1000],
        [1735804800, 104.0, 108.0, 103.0, 107.0, 1200],
    ]
}


async def test_groww_adapter_fetch_historical_happy_path() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI, "get_historical_candles", return_value=_HISTORICAL_RESPONSE
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        bars = await adapter.fetch_historical(
            "NSE-RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
        )

    assert len(bars) == 2
    assert bars[0].close == 104.0
    assert bars[0].provider == "groww"
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_auth_expired() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPIAuthenticationException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(AuthExpiredError):
            await adapter.fetch_historical(
                "NSE-RELIANCE",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_rate_limited() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPIRateLimitException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(RateLimitError):
            await adapter.fetch_historical(
                "NSE-RELIANCE",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_generic_error_wrapped() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPINotFoundException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(DataUnavailableError):
            await adapter.fetch_historical(
                "NOT_A_REAL_SYMBOL",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()


async def test_groww_adapter_api_secret_flow_calls_get_access_token_with_secret() -> (
    None
):
    with patch.object(
        GrowwAPI, "get_access_token", return_value="fake-token"
    ) as mock_get_token:
        adapter = GrowwAdapter(api_key="key", api_secret="my-secret")
        await adapter.connect()

    mock_get_token.assert_called_once_with(api_key="key", secret="my-secret")
    await adapter.disconnect()


def test_groww_adapter_requires_exactly_one_auth_secret() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GrowwAdapter(api_key="key")

    with pytest.raises(ValueError, match="exactly one"):
        GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP", api_secret="s")


_INSTRUMENT_ROW: dict[str, str] = {
    "exchange": "NSE",
    "segment": "CASH",
    "exchange_token": "500325",
}


class FakeGrowwFeed:
    instances: ClassVar[list["FakeGrowwFeed"]] = []

    def __init__(self, groww_api: object) -> None:
        self.groww_api = groww_api
        self.subscribed: list[dict[str, str]] | None = None
        self.unsubscribed: list[dict[str, str]] | None = None
        self._on_data_received: Any = None
        self._ltp_data: dict[str, Any] = {}
        FakeGrowwFeed.instances.append(self)

    def subscribe_ltp(
        self, instrument_list: list[dict[str, str]], on_data_received: Any = None
    ) -> None:
        self.subscribed = instrument_list
        self._on_data_received = on_data_received

    def unsubscribe_ltp(self, instrument_list: list[dict[str, str]]) -> None:
        self.unsubscribed = instrument_list

    def get_ltp(self) -> dict[str, Any]:
        return self._ltp_data

    def push_tick(
        self, exchange: str, segment: str, exchange_token: str, ltp: float
    ) -> None:
        self._ltp_data = {
            exchange: {
                segment: {
                    exchange_token: {
                        "ltp": ltp,
                        "volume": 100,
                        "tsInMillis": 1735718400000,
                    }
                }
            }
        }
        self._on_data_received(
            {"exchange": exchange, "segment": segment, "feed_key": exchange_token}
        )


async def test_groww_adapter_subscribe_live_happy_path() -> None:
    FakeGrowwFeed.instances.clear()

    with (
        patch.object(
            GrowwAPI, "get_instrument_by_groww_symbol", return_value=_INSTRUMENT_ROW
        ),
        patch("ingest.adapters.groww.adapter.GrowwFeed", FakeGrowwFeed),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        adapter._client = GrowwAPI("fake-token")

        agen = adapter.subscribe_live(["NSE-RELIANCE"])
        first_tick_task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0)

        feed = FakeGrowwFeed.instances[-1]
        assert feed.subscribed == [_INSTRUMENT_ROW]

        feed.push_tick("NSE", "CASH", "500325", ltp=4084.0)

        tick = await first_tick_task
        assert tick.symbol == "NSE-RELIANCE"
        assert tick.price == 4084.0
        assert tick.provider == "groww"

        await agen.aclose()
        assert feed.unsubscribed == [_INSTRUMENT_ROW]
        await adapter.disconnect()
