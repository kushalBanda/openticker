"""Quotes and historical candles from Kite Connect — translation of Kite's
responses into `Quote` / `Bar`. Both calls need a session access token
(from `connect_broker`); instruments are addressed by Kite's own
`exchange:tradingsymbol` (quotes) or `instrument_token` (candles).
"""

import time
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from openticker.adapters.brokers.zerodha.auth import KITE_BASE_URL
from openticker.ports.errors import BrokerError, BrokerRateLimitError, BrokerSessionError
from openticker.ports.models import Bar, Instrument, Interval, Quote

_IST = ZoneInfo("Asia/Kolkata")

# Kite names its intervals exactly as `Interval` does. Value: the most days one
# historical request may span for that interval (Kite rejects longer ranges).
MAX_DAYS_PER_REQUEST: dict[str, int] = {
    Interval.MINUTE: 60,
    Interval.MINUTE_3: 100,
    Interval.MINUTE_5: 100,
    Interval.MINUTE_10: 100,
    Interval.MINUTE_15: 200,
    Interval.MINUTE_30: 200,
    Interval.MINUTE_60: 400,
    Interval.DAY: 2000,
}

# Kite allows 3 historical requests/second; stay under it between chunks.
_SECONDS_BETWEEN_CHUNKS = 0.35


class KiteApiError(BrokerError):
    """Kite returned an error for a market-data call."""


class KiteRateLimitError(KiteApiError, BrokerRateLimitError):
    """Kite answered 429."""


class KiteSessionError(KiteApiError, BrokerSessionError):
    """The stored access token is missing, expired, or revoked — reconnect the broker."""


class InvalidCandleRequestError(BrokerError, ValueError):
    """Unknown interval, or a date range that ends before it starts."""


# Kite answers at most this many instruments per /quote call.
MAX_QUOTES_PER_REQUEST = 500


def fetch_quote(api_key: str, access_token: str, instrument: Instrument) -> Quote:
    key = _quote_key(instrument)
    payload = _get(api_key, access_token, "/quote", params={"i": key})
    data: dict[str, Any] | None = payload["data"].get(key)
    if data is None:
        raise KiteApiError(f"Kite returned no quote for {key}")
    return _to_quote(instrument, data)


def fetch_quotes(api_key: str, access_token: str, instruments: Sequence[Instrument]) -> list[Quote]:
    """Quotes for many instruments, batched. Instruments Kite has no quote for
    (untraded or unknown) are left out."""
    quotes: list[Quote] = []
    for start in range(0, len(instruments), MAX_QUOTES_PER_REQUEST):
        batch = instruments[start : start + MAX_QUOTES_PER_REQUEST]
        payload = _get(
            api_key, access_token, "/quote", params=tuple(("i", _quote_key(item)) for item in batch)
        )
        data: dict[str, dict[str, Any]] = payload["data"]
        quotes.extend(
            _to_quote(item, data[_quote_key(item)]) for item in batch if _quote_key(item) in data
        )
    return quotes


def _quote_key(instrument: Instrument) -> str:
    return f"{instrument.broker_exchange}:{instrument.broker_symbol}"


def _to_quote(instrument: Instrument, data: dict[str, Any]) -> Quote:
    open_interest = data.get("oi")
    volume = data.get("volume")
    ohlc: dict[str, Any] = data.get("ohlc") or {}
    depth: dict[str, list[dict[str, Any]]] = data.get("depth") or {}
    buy, sell = _top(depth.get("buy")), _top(depth.get("sell"))
    return Quote(
        instrument=instrument,
        last_price=float(data["last_price"]),
        as_of=_quote_time(data),
        open_interest=int(open_interest) if open_interest is not None else None,
        day_high=_price(ohlc.get("high")),
        day_low=_price(ohlc.get("low")),
        bid=_price(buy.get("price")),
        ask=_price(sell.get("price")),
        bid_quantity=int(buy["quantity"]) if _price(buy.get("price")) else None,
        ask_quantity=int(sell["quantity"]) if _price(sell.get("price")) else None,
        open=_price(ohlc.get("open")),
        close=_price(ohlc.get("close")),
        volume=int(volume) if volume is not None else None,
    )


def _top(levels: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The best level of one side of the book. Kite fills empty levels with
    price 0, which `_price` reads as none."""
    return levels[0] if levels else {}


def _price(value: Any) -> float | None:
    return float(value) if value else None


def fetch_candles(
    api_key: str, access_token: str, instrument: Instrument, interval: str, start: date, end: date
) -> list[Bar]:
    """All candles from `start` through `end`, inclusive. Any failed chunk
    raises — a partial range is never returned."""
    max_days = MAX_DAYS_PER_REQUEST.get(interval)
    if max_days is None:
        raise InvalidCandleRequestError(
            f"unknown interval {interval!r}; expected one of {sorted(MAX_DAYS_PER_REQUEST)}"
        )
    if end < start:
        raise InvalidCandleRequestError(f"end {end} is before start {start}")

    bars: list[Bar] = []
    for index, (chunk_start, chunk_end) in enumerate(_chunks(start, end, max_days)):
        if index:
            time.sleep(_SECONDS_BETWEEN_CHUNKS)
        payload = _get(
            api_key,
            access_token,
            f"/instruments/historical/{instrument.token}/{interval}",
            params={
                "from": f"{chunk_start.isoformat()} 00:00:00",
                "to": f"{chunk_end.isoformat()} 23:59:59",
            },
        )
        bars.extend(_to_bar(instrument, interval, candle) for candle in payload["data"]["candles"])
    return bars


def _chunks(start: date, end: date, max_days: int) -> Iterator[tuple[date, date]]:
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=max_days - 1), end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end + timedelta(days=1)


def _to_bar(instrument: Instrument, interval: str, candle: list[Any]) -> Bar:
    timestamp, open_, high, low, close, volume = candle[:6]
    return Bar(
        instrument=instrument,
        interval=interval,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=int(volume),
        timestamp=datetime.fromisoformat(timestamp).astimezone(UTC),
    )


def _quote_time(data: dict[str, Any]) -> datetime:
    """Kite sends exchange-local (IST) times without an offset. Indices have no
    `last_trade_time`, so fall back to the quote's own `timestamp`."""
    raw: str | None = data.get("last_trade_time") or data.get("timestamp")
    if raw is None:
        return datetime.now(UTC)
    return datetime.fromisoformat(raw).replace(tzinfo=_IST).astimezone(UTC)


def _get(
    api_key: str,
    access_token: str,
    path: str,
    params: dict[str, str] | tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    with httpx.Client(base_url=KITE_BASE_URL, timeout=30.0) as client:
        response = client.get(
            path,
            params=params,
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {api_key}:{access_token}",
            },
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise KiteSessionError(
            "Kite rejected the session token (expired or revoked) — "
            "reconnect with get_broker_login_url + connect_broker"
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise KiteRateLimitError(f"Kite {path} is rate limited (HTTP 429); wait before retrying")
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise KiteApiError(f"Kite {path} failed: HTTP {response.status_code} - {response.text}")
    payload: dict[str, Any] = response.json()
    return payload
