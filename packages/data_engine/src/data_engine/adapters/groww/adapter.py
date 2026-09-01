import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import pyotp
from growwapi import GrowwAPI
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPIAuthorisationException,
    GrowwAPIException,
    GrowwAPIRateLimitException,
)

from data_engine.adapters.groww.intervals import GROWW_INTERVAL_MAP
from data_engine.adapters.groww.mapper import map_candle_to_bar
from data_engine.core.constants import (
    GROWW_NON_TRADING_REQUESTS_PER_SECOND,
    PROVIDER_GROWW,
)
from data_engine.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from data_engine.core.intervals import register_interval_map, to_provider_interval
from data_engine.core.models import Bar, Tick
from data_engine.core.rate_limiter import RateLimiter
from data_engine.core.registry import register_adapter

register_interval_map(PROVIDER_GROWW, GROWW_INTERVAL_MAP)


@register_adapter(PROVIDER_GROWW)
class GrowwAdapter:
    def __init__(self, api_key: str, totp_secret: str) -> None:
        self._api_key = api_key
        self._totp_secret = totp_secret
        self._client: GrowwAPI | None = None
        self._rate_limiter = RateLimiter(GROWW_NON_TRADING_REQUESTS_PER_SECOND)

    async def connect(self) -> None:
        totp = pyotp.TOTP(self._totp_secret).now()
        access_token = await asyncio.to_thread(
            GrowwAPI.get_access_token, api_key=self._api_key, totp=totp
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
        raise NotImplementedError("Groww live tick subscription lands in Slice 8")
        yield

    async def disconnect(self) -> None:
        self._client = None
