from datetime import UTC, datetime, timedelta
from typing import Any

from data_engine.core.constants import PROVIDER_KITE
from data_engine.core.models import Bar, Tick

# Kite's WebSocket ticks carry exchange_timestamp/last_trade_time as naive
# datetimes. Assumed to be IST (the SDK exposes no tzinfo and Kite is an
# Indian exchange), not independently confirmed against a live packet.
_IST_OFFSET = timedelta(hours=5, minutes=30)


def map_candle_to_bar(raw: list[Any], symbol: str, interval: str) -> Bar:
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


def map_tick(raw: dict[str, Any], symbol: str) -> Tick:
    naive_ts = raw.get("exchange_timestamp") or raw.get("last_trade_time")
    ts = (naive_ts - _IST_OFFSET).replace(tzinfo=UTC) if naive_ts else datetime.now(UTC)
    return Tick(
        symbol=symbol,
        ts=ts,
        price=float(raw["last_price"]),
        volume=int(raw.get("volume_traded", 0)),
        provider=PROVIDER_KITE,
    )
