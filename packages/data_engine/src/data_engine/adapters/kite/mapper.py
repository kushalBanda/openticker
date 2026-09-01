from datetime import datetime
from typing import Any

from data_engine.core.constants import PROVIDER_KITE
from data_engine.core.models import Bar


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
