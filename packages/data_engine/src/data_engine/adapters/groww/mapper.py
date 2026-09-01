from datetime import UTC, datetime
from typing import Any

from data_engine.core.constants import PROVIDER_GROWW
from data_engine.core.models import Bar


def map_candle_to_bar(raw: list[Any], symbol: str, interval: str) -> Bar:
    ts_epoch, open_, high, low, close, volume = raw[:6]
    ts = datetime.fromtimestamp(ts_epoch, tz=UTC)
    return Bar(
        symbol=symbol,
        interval=interval,
        ts=ts,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=int(volume),
        provider=PROVIDER_GROWW,
    )
