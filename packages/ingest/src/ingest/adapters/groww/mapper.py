from datetime import UTC, datetime
from typing import Any

from ingest.core.constants import PROVIDER_GROWW
from ingest.core.models import Bar, Tick


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


def map_tick(raw: dict[str, Any], symbol: str) -> Tick:
    # Field names confirmed from growwapi's own StocksSocketResponseProtoDto
    # (proto field names: ltp, volume, tsInMillis), not documented anywhere,
    # source-inspected against the installed SDK.
    ts_millis = raw.get("tsInMillis")
    ts = (
        datetime.fromtimestamp(int(ts_millis) / 1000, tz=UTC)
        if ts_millis
        else datetime.now(UTC)
    )
    return Tick(
        symbol=symbol,
        ts=ts,
        price=float(raw["ltp"]),
        volume=int(raw.get("volume", 0)),
        provider=PROVIDER_GROWW,
    )
