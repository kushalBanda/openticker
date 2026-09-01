import asyncio
import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import patch

import httpx
import pytest
import respx
from data_engine.adapters.kite.adapter import KiteAdapter
from data_engine.core.constants import KITE_BASE_URL
from data_engine.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)

_INSTRUMENTS_CSV = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,"
    "strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    "128083204,500325,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
)

_HISTORICAL_RESPONSE = {
    "status": "success",
    "data": {
        "candles": [
            ["2026-01-02T00:00:00+0000", 100.0, 105.0, 99.0, 104.0, 1000],
            ["2026-01-03T00:00:00+0000", 104.0, 108.0, 103.0, 107.0, 1200],
        ]
    },
}


@respx.mock
async def test_kite_adapter_fetch_historical_happy_path() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_INSTRUMENTS_CSV)
    )
    respx.get(url__regex=re.escape(KITE_BASE_URL) + r"/instruments/historical/.*").mock(
        return_value=httpx.Response(200, json=_HISTORICAL_RESPONSE)
    )

    adapter = KiteAdapter(api_key="key", access_token="token")
    await adapter.connect()

    bars = await adapter.fetch_historical(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 4, tzinfo=UTC),
    )

    assert len(bars) == 2
    assert bars[0].close == 104.0
    assert bars[0].provider == "kite"
    await adapter.disconnect()


@respx.mock
async def test_kite_adapter_fetch_historical_auth_expired() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_INSTRUMENTS_CSV)
    )
    respx.get(url__regex=re.escape(KITE_BASE_URL) + r"/instruments/historical/.*").mock(
        return_value=httpx.Response(403)
    )

    adapter = KiteAdapter(api_key="key", access_token="expired")
    await adapter.connect()

    with pytest.raises(AuthExpiredError):
        await adapter.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
        )
    await adapter.disconnect()


@respx.mock
async def test_kite_adapter_fetch_historical_rate_limited() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_INSTRUMENTS_CSV)
    )
    respx.get(url__regex=re.escape(KITE_BASE_URL) + r"/instruments/historical/.*").mock(
        return_value=httpx.Response(429)
    )

    adapter = KiteAdapter(api_key="key", access_token="token")
    await adapter.connect()

    with pytest.raises(RateLimitError):
        await adapter.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
        )
    await adapter.disconnect()


@respx.mock
async def test_kite_adapter_fetch_historical_unknown_symbol_propagates() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_INSTRUMENTS_CSV)
    )

    adapter = KiteAdapter(api_key="key", access_token="token")
    await adapter.connect()

    with pytest.raises(DataUnavailableError):
        await adapter.fetch_historical(
            "NOT_A_REAL_SYMBOL",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
        )
    await adapter.disconnect()


class FakeKiteTicker:
    instances: ClassVar[list["FakeKiteTicker"]] = []

    def __init__(self, api_key: str, access_token: str) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self.subscribed_tokens: list[int] | None = None
        self.closed = False
        FakeKiteTicker.instances.append(self)

    def connect(self, threaded: bool = False) -> None:
        self.on_connect(self, {})

    def close(self, code: object = None, reason: object = None) -> None:
        self.closed = True

    def subscribe(self, tokens: list[int]) -> None:
        self.subscribed_tokens = tokens


@respx.mock
async def test_kite_adapter_subscribe_live_happy_path() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_INSTRUMENTS_CSV)
    )
    FakeKiteTicker.instances.clear()

    with patch("data_engine.adapters.kite.adapter.KiteTicker", FakeKiteTicker):
        adapter = KiteAdapter(api_key="key", access_token="token")
        await adapter.connect()

        agen = adapter.subscribe_live(["RELIANCE"])
        first_tick_task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0)

        ticker = FakeKiteTicker.instances[-1]
        assert ticker.subscribed_tokens == [128083204]

        raw_tick: dict[str, Any] = {
            "instrument_token": 128083204,
            "last_price": 4084.0,
            "volume_traded": 12510,
            # naive, matching Kite's real (undocumented timezone) tick shape
            "exchange_timestamp": datetime(2026, 1, 15, 13, 16, 56),
        }
        ticker.on_ticks(ticker, [raw_tick])

        tick = await first_tick_task
        assert tick.symbol == "RELIANCE"
        assert tick.price == 4084.0

        await agen.aclose()
        assert ticker.closed
        await adapter.disconnect()
