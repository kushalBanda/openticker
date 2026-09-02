import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pyotp
from growwapi import GrowwAPI, GrowwFeed
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPIAuthorisationException,
    GrowwAPIException,
    GrowwAPIRateLimitException,
)

from ingest.adapters.groww.intervals import GROWW_INTERVAL_MAP
from ingest.adapters.groww.mapper import map_candle_to_bar, map_tick
from ingest.core.constants import (
    GROWW_NON_TRADING_REQUESTS_PER_SECOND,
    PROVIDER_GROWW,
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

register_interval_map(PROVIDER_GROWW, GROWW_INTERVAL_MAP)


@register_adapter(PROVIDER_GROWW)
class GrowwAdapter:
    def __init__(
        self,
        api_key: str,
        totp_secret: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        if (totp_secret is None) == (api_secret is None):
            raise ValueError(
                "GrowwAdapter requires exactly one of totp_secret or api_secret"
            )
        self._api_key = api_key
        self._totp_secret = totp_secret
        self._api_secret = api_secret
        self._client: GrowwAPI | None = None
        self._rate_limiter = RateLimiter(GROWW_NON_TRADING_REQUESTS_PER_SECOND)
        self._feed: GrowwFeed | None = None
        self._feed_instruments: list[dict[str, str]] = []

    async def connect(self) -> None:
        if self._totp_secret is not None:
            totp = pyotp.TOTP(self._totp_secret).now()
            access_token = await asyncio.to_thread(
                GrowwAPI.get_access_token, api_key=self._api_key, totp=totp
            )
        else:
            access_token = await asyncio.to_thread(
                GrowwAPI.get_access_token,
                api_key=self._api_key,
                secret=self._api_secret,
            )
        self._client = GrowwAPI(access_token)

    async def fetch_historical(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]:
        if self._client is None:
            raise DataUnavailableError(
                "GrowwAdapter.connect() must be called before use"
            )

        groww_interval = to_provider_interval(PROVIDER_GROWW, interval)
        await self._rate_limiter.acquire()

        try:
            response = await asyncio.to_thread(
                self._client.get_historical_candles,
                exchange=self._client.EXCHANGE_NSE,
                segment=self._client.SEGMENT_CASH,
                groww_symbol=symbol,
                start_time=from_.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=to.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval=groww_interval,
            )
        except (GrowwAPIAuthenticationException, GrowwAPIAuthorisationException) as exc:
            raise AuthExpiredError(
                "Groww session expired during fetch_historical"
            ) from exc
        except GrowwAPIRateLimitException as exc:
            raise RateLimitError(
                "Groww rejected the call for exceeding its rate limit"
            ) from exc
        except GrowwAPIException as exc:
            raise DataUnavailableError(
                f"Groww historical fetch failed for {symbol!r}: {exc.msg}"
            ) from exc

        candles = response["candles"]
        return [map_candle_to_bar(c, symbol, interval) for c in candles]

    async def subscribe_live(self, symbols: list[str]) -> AsyncIterator[Tick]:
        if self._client is None:
            raise DataUnavailableError(
                "GrowwAdapter.connect() must be called before use"
            )

        # Ground truth for exchange/segment/exchange_token and the ltp/volume/
        # tsInMillis field names, source-verified against the installed
        # growwapi SDK (proto_parser.py, feed.py, constants.py), not
        # documented anywhere and not run against a live connection.
        instrument_rows = {
            s: self._client.get_instrument_by_groww_symbol(s) for s in symbols
        }
        instrument_list = [
            {
                "exchange": row["exchange"],
                "segment": row["segment"],
                "exchange_token": row["exchange_token"],
            }
            for row in instrument_rows.values()
        ]
        key_to_symbol = {
            (row["exchange"], row["segment"], row["exchange_token"]): symbol
            for symbol, row in instrument_rows.items()
        }

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Tick | Exception] = asyncio.Queue()
        feed = GrowwFeed(self._client)

        def on_data_received(meta: dict[str, Any]) -> None:
            try:
                key = (meta["exchange"], meta["segment"], meta["feed_key"])
                symbol = key_to_symbol.get(key)
                if symbol is None:
                    return
                ltp_data = (
                    feed.get_ltp()
                    .get(meta["exchange"], {})
                    .get(meta["segment"], {})
                    .get(meta["feed_key"])
                )
                if ltp_data is None:
                    return
                tick = map_tick(ltp_data, symbol)
                loop.call_soon_threadsafe(queue.put_nowait, tick)
            except Exception as exc:
                error = DataUnavailableError(f"Groww feed callback failed: {exc}")
                loop.call_soon_threadsafe(queue.put_nowait, error)

        self._feed = feed
        self._feed_instruments = instrument_list
        feed.subscribe_ltp(instrument_list, on_data_received=on_data_received)

        try:
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            feed.unsubscribe_ltp(instrument_list)
            self._feed = None
            self._feed_instruments = []

    async def disconnect(self) -> None:
        if self._feed is not None and self._feed_instruments:
            self._feed.unsubscribe_ltp(self._feed_instruments)
            self._feed = None
            self._feed_instruments = []
        self._client = None
