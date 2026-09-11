"""fetch_bars MCP tool (quant-engine server): historical OHLCV bars for one symbol."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import Field

from engine.core.data import connect_engine, fetch_symbol_bars
from engine.core.serialization import to_json_dict


async def fetch_bars(
    symbol: Annotated[str, Field(description='Tradingsymbol to fetch, e.g. "RELIANCE" (not "NSE:RELIANCE").')],
    interval: Annotated[
        str, Field(description='Canonical bar interval, e.g. "1d" (daily), "1m" (1-minute).')
    ] = "1d",
    days: Annotated[
        int, Field(description="Lookback window in days from now.", gt=0)
    ] = 365,
    provider: Annotated[
        str | None,
        Field(
            description=(
                'Provider name, e.g. "kite". Omit to use whichever provider connected '
                "most recently."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Fetch historical OHLCV bars for one symbol through a connected adapter.

    Returns:
        A dict with the resolved provider, symbol, interval, bar count,
        first/last close, and the full serialized bar list (open/high/
        low/close/volume/ts per bar).

    Raises:
        engine.core.exceptions.NotConnectedError: No adapter is connected.
        engine.core.exceptions.SessionExpiredError: The stored session expired.
        engine.core.exceptions.ProviderRateLimitedError: The provider
            rejected a connect/fetch call for exceeding its rate limit.
        ingest.core.exceptions.DataUnavailableError: No bars in range.
    """
    resolved_provider, data_engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    bars = await fetch_symbol_bars(data_engine, resolved_provider, symbol, interval, frm, to)

    return {
        "provider": resolved_provider,
        "symbol": symbol,
        "interval": interval,
        "bar_count": len(bars),
        "first_close": bars[0].close,
        "last_close": bars[-1].close,
        "bars": to_json_dict(bars),
    }
