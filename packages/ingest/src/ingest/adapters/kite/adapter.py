import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from kiteconnect import KiteTicker

from ingest.adapters.kite.instrument_master import InstrumentMaster
from ingest.adapters.kite.intervals import KITE_INTERVAL_MAP
from ingest.adapters.kite.mapper import map_candle_to_bar, map_tick
from ingest.core.constants import (
    KITE_BASE_URL,
    KITE_HISTORICAL_REQUESTS_PER_SECOND,
    PROVIDER_KITE,
    kite_auth_headers,
)
from ingest.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from ingest.core.intervals import register_interval_map, to_provider_interval
from ingest.core.models import Bar, Tick
from ingest.core.rate_limiter import RateLimiter
from ingest.core.registry import register_adapter

register_interval_map(PROVIDER_KITE, KITE_INTERVAL_MAP)


@register_adapter(PROVIDER_KITE)
class KiteAdapter:
    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._http = httpx.AsyncClient(base_url=KITE_BASE_URL)
        self._instrument_master = InstrumentMaster(api_key, access_token, self._http)
        self._rate_limiter = RateLimiter(KITE_HISTORICAL_REQUESTS_PER_SECOND)
        self._ticker: KiteTicker | None = None

    async def connect(self) -> None:
        await self._instrument_master.refresh()

    async def fetch_historical(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]:
        instrument_token = self._instrument_master.resolve(symbol)
        kite_interval = to_provider_interval(PROVIDER_KITE, interval)

        await self._rate_limiter.acquire()
        response = await self._http.get(
            f"/instruments/historical/{instrument_token}/{kite_interval}",
            params={
                "from": from_.strftime("%Y-%m-%d %H:%M:%S"),
                "to": to.strftime("%Y-%m-%d %H:%M:%S"),
            },
            headers=kite_auth_headers(self._api_key, self._access_token),
        )

        if response.status_code == HTTPStatus.FORBIDDEN:
            raise AuthExpiredError("Kite session expired during fetch_historical")
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise RateLimitError("Kite rejected the call for exceeding its rate limit")
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            raise DataUnavailableError(
                f"Kite historical fetch failed for {symbol!r}: HTTP {response.status_code}"
            )

        candles = response.json()["data"]["candles"]
        return [map_candle_to_bar(c, symbol, interval) for c in candles]

    async def subscribe_live(self, symbols: list[str]) -> AsyncIterator[Tick]:
        token_to_symbol = {self._instrument_master.resolve(s): s for s in symbols}
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Tick | Exception] = asyncio.Queue()

        ticker = KiteTicker(self._api_key, self._access_token)

        def on_ticks(_ws: object, ticks: list[dict[str, Any]]) -> None:
            for raw in ticks:
                symbol = token_to_symbol.get(raw["instrument_token"])
                if symbol is None:
                    continue
                tick = map_tick(raw, symbol)
                loop.call_soon_threadsafe(queue.put_nowait, tick)

        def on_connect(ws: KiteTicker, _response: object) -> None:
            ws.subscribe(list(token_to_symbol))

        def on_close(_ws: object, code: int, reason: str) -> None:
            error = AuthExpiredError(f"Kite WebSocket closed: {code} {reason}")
            loop.call_soon_threadsafe(queue.put_nowait, error)

        def on_error(_ws: object, code: int, reason: str) -> None:
            error = DataUnavailableError(f"Kite WebSocket error: {code} {reason}")
            loop.call_soon_threadsafe(queue.put_nowait, error)

        ticker.on_ticks = on_ticks
        ticker.on_connect = on_connect
        ticker.on_close = on_close
        ticker.on_error = on_error
        self._ticker = ticker

        ticker.connect(threaded=True)

        try:
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            ticker.close()
            self._ticker = None

    async def disconnect(self) -> None:
        if self._ticker is not None:
            self._ticker.close()
            self._ticker = None
        await self._http.aclose()
