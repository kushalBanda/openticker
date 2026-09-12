"""Flat Kite Connect mechanics: auth exchange, instrument lookup, historical fetch.

Ported from ingest.adapters.kite.{adapter,instrument_master,mapper,intervals}
and ingest.core.rate_limiter, collapsed into one module with no adapter
Protocol, no @register_adapter, no AdapterFactory lookup. Live-tick
subscription is dropped: no skill script needs it (see the design spec's
"not ported" list).
"""

import asyncio
import csv
import io
import time
from datetime import datetime
from hashlib import sha256
from http import HTTPStatus
from typing import Any, Final

import httpx

from lib.mechanics.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from lib.mechanics.models import Bar

PROVIDER_KITE: Final = "kite"
KITE_BASE_URL: Final = "https://api.kite.trade"
KITE_API_VERSION: Final = "3"
KITE_HISTORICAL_REQUESTS_PER_SECOND: Final = 3.0
INSTRUMENT_MASTER_REFRESH_HOURS: Final = 24

KITE_INTERVAL_MAP: dict[str, str] = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "60m": "60minute",
    "1d": "day",
}


def kite_auth_headers(api_key: str, access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {api_key}:{access_token}",
        "X-Kite-Version": KITE_API_VERSION,
    }


def exchange_request_token(api_key: str, api_secret: str, request_token: str) -> str:
    """Exchange a request_token for an access_token via Kite's session API.

    Args:
        api_key: The registered Kite Connect app's API key.
        api_secret: The registered Kite Connect app's API secret.
        request_token: The token caught from Zerodha's OAuth redirect.

    Returns:
        The resulting access_token.

    Raises:
        AuthExpiredError: Kite's API returned a non-2xx response.
    """
    checksum = sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    with httpx.Client(base_url=KITE_BASE_URL) as http:
        response = http.post(
            "/session/token",
            data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
        )
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise AuthExpiredError(f"Kite login exchange failed: HTTP {response.status_code} - {response.text}")
    access_token: str = response.json()["data"]["access_token"]
    return access_token


class RateLimiter:
    def __init__(self, calls_per_second: float) -> None:
        self._min_interval = 1.0 / calls_per_second
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                elapsed = now - self._last_call
                wait = self._min_interval - elapsed
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call = time.monotonic()


async def _fetch_instrument_token(
    http: httpx.AsyncClient, api_key: str, access_token: str, tradingsymbol: str
) -> int:
    """Resolve one tradingsymbol to its Kite instrument_token.

    Fetches Kite's full instrument-master CSV on every call - callers that
    fetch many symbols in one process should cache this themselves; kept
    simple here since each skill script is a short-lived process.
    """
    response = await http.get("/instruments", headers=kite_auth_headers(api_key, access_token))
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise AuthExpiredError("Kite session expired while fetching instrument master")
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        if row["tradingsymbol"] == tradingsymbol:
            return int(row["instrument_token"])
    raise DataUnavailableError(f"{tradingsymbol!r} not found in Kite instrument master")


def _map_candle_to_bar(raw: list[Any], symbol: str, interval: str) -> Bar:
    ts_str, open_, high, low, close, volume = raw[:6]
    ts = datetime.fromisoformat(ts_str)
    return Bar(
        symbol=symbol,
        interval=interval,
        ts=ts,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=int(volume),
        provider=PROVIDER_KITE,
    )


_rate_limiter = RateLimiter(KITE_HISTORICAL_REQUESTS_PER_SECOND)


async def fetch_kite_historical(
    api_key: str, access_token: str, symbol: str, interval: str, frm: datetime, to: datetime
) -> list[Bar]:
    """Fetch historical OHLCV bars for one symbol directly from Kite's API.

    Args:
        api_key: The connected Kite app's API key.
        access_token: The connected session's access token.
        symbol: Tradingsymbol to fetch, e.g. "RELIANCE".
        interval: Canonical bar interval, e.g. "1d".
        frm: Range start (inclusive).
        to: Range end (inclusive).

    Returns:
        Bars sorted ascending by timestamp.

    Raises:
        AuthExpiredError: The session was rejected as expired.
        RateLimitError: Kite rejected the call for exceeding its rate limit.
        DataUnavailableError: The symbol was not found, or Kite returned
            a non-2xx response for another reason.
    """
    kite_interval = KITE_INTERVAL_MAP.get(interval)
    if kite_interval is None:
        raise DataUnavailableError(f"unsupported interval {interval!r} for Kite")

    async with httpx.AsyncClient(base_url=KITE_BASE_URL) as http:
        instrument_token = await _fetch_instrument_token(http, api_key, access_token, symbol)

        await _rate_limiter.acquire()
        response = await http.get(
            f"/instruments/historical/{instrument_token}/{kite_interval}",
            params={
                "from": frm.strftime("%Y-%m-%d %H:%M:%S"),
                "to": to.strftime("%Y-%m-%d %H:%M:%S"),
            },
            headers=kite_auth_headers(api_key, access_token),
        )

    if response.status_code == HTTPStatus.FORBIDDEN:
        raise AuthExpiredError("Kite session expired during historical fetch")
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise RateLimitError("Kite rejected the call for exceeding its rate limit")
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise DataUnavailableError(f"Kite historical fetch failed for {symbol!r}: HTTP {response.status_code}")

    candles = response.json()["data"]["candles"]
    return [_map_candle_to_bar(c, symbol, interval) for c in candles]
