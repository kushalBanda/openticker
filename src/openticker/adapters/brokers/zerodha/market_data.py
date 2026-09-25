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
from openticker.ports.models import Bar, DepthLevel, Instrument, Interval, MarketDepth, Quote

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
    return _to_quote(instrument, _full_quote(api_key, access_token, instrument))


def fetch_depth(api_key: str, access_token: str, instrument: Instrument) -> MarketDepth:
    """The same /quote call as `fetch_quote`: Kite's full quote carries the
    five best levels of each side."""
    return _to_depth(instrument, _full_quote(api_key, access_token, instrument))


def _full_quote(api_key: str, access_token: str, instrument: Instrument) -> dict[str, Any]:
    key = _quote_key(instrument)
    payload = _get(api_key, access_token, "/quote", params={"i": key})
    data: dict[str, Any] | None = payload["data"].get(key)
    if data is None:
        raise KiteApiError(f"Kite returned no quote for {key}")
    return data


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
    bids, asks = _book(data)
    best_bid, best_ask = bids[0] if bids else None, asks[0] if asks else None
    return Quote(
        instrument=instrument,
        last_price=float(data["last_price"]),
        as_of=_quote_time(data),
        open_interest=int(open_interest) if open_interest is not None else None,
        day_high=_price(ohlc.get("high")),
        day_low=_price(ohlc.get("low")),
        bid=best_bid.price if best_bid else None,
        ask=best_ask.price if best_ask else None,
        bid_quantity=best_bid.quantity if best_bid else None,
        ask_quantity=best_ask.quantity if best_ask else None,
        open=_price(ohlc.get("open")),
        close=_price(ohlc.get("close")),
        volume=int(volume) if volume is not None else None,
    )


def _to_depth(instrument: Instrument, data: dict[str, Any]) -> MarketDepth:
    ohlc: dict[str, Any] = data.get("ohlc") or {}
    bids, asks = _book(data)
    return MarketDepth(
        instrument=instrument,
        as_of=_quote_time(data),
        last_price=float(data["last_price"]),
        last_quantity=_count(data.get("last_quantity")),
        bids=bids,
        asks=asks,
        total_buy_quantity=int(data.get("buy_quantity") or 0),
        total_sell_quantity=int(data.get("sell_quantity") or 0),
        open=_price(ohlc.get("open")),
        high=_price(ohlc.get("high")),
        low=_price(ohlc.get("low")),
        close=_price(ohlc.get("close")),
        volume=_count(data.get("volume")),
        open_interest=_count(data.get("oi")),
    )


# Levels read per side of the book, as openalgo reads them; Kite's /quote sends five.
DEPTH_LEVELS = 5


def _book(data: dict[str, Any]) -> tuple[tuple[DepthLevel, ...], tuple[DepthLevel, ...]]:
    """Bids and asks, best first, as Kite orders them. The one reading of the
    book that quotes (best bid and ask) and depth both use."""
    depth: dict[str, list[dict[str, Any]]] = data.get("depth") or {}
    return _levels(depth.get("buy")), _levels(depth.get("sell"))


def _levels(levels: list[dict[str, Any]] | None) -> tuple[DepthLevel, ...]:
    """Kite pads empty levels with price 0; those are left out."""
    return tuple(
        DepthLevel(
            price=float(level["price"]),
            quantity=int(level.get("quantity") or 0),
            orders=int(level.get("orders") or 0),
        )
        for level in (levels or [])[:DEPTH_LEVELS]
        if level.get("price")
    )


def _count(value: Any) -> int | None:
    return int(value) if value is not None else None


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
        response = client.get(path, params=params, headers=kite_headers(api_key, access_token))
    return kite_payload(path, response)


def kite_headers(api_key: str, access_token: str) -> dict[str, str]:
    return {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"}


def kite_payload(path: str, response: httpx.Response) -> dict[str, Any]:
    """The JSON of a Kite answer; its refusals become the errors above."""
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
