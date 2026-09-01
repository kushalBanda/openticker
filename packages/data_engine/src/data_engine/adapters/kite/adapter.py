from collections.abc import AsyncIterator
from datetime import datetime
from http import HTTPStatus

import httpx

from data_engine.adapters.kite import (
    intervals as _register_kite_intervals,  # noqa: F401
)
from data_engine.adapters.kite.instrument_master import InstrumentMaster
from data_engine.adapters.kite.mapper import map_candle_to_bar
from data_engine.core.constants import (
    KITE_BASE_URL,
    KITE_HISTORICAL_REQUESTS_PER_SECOND,
    PROVIDER_KITE,
    kite_auth_headers,
)
from data_engine.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from data_engine.core.intervals import to_provider_interval
from data_engine.core.models import Bar, Tick
from data_engine.core.rate_limiter import RateLimiter
from data_engine.core.registry import register_adapter


@register_adapter(PROVIDER_KITE)
class KiteAdapter:
    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._http = httpx.AsyncClient(base_url=KITE_BASE_URL)
        self._instrument_master = InstrumentMaster(api_key, access_token, self._http)
        self._rate_limiter = RateLimiter(KITE_HISTORICAL_REQUESTS_PER_SECOND)

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
        raise NotImplementedError("Kite live tick subscription lands in Slice 7")
        yield  # pragma: no cover

    async def disconnect(self) -> None:
        await self._http.aclose()
