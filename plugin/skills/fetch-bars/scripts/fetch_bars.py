#!/usr/bin/env python3
"""fetch-bars skill script: historical OHLCV bars for one symbol.

Run as: uv run python plugin/skills/fetch-bars/scripts/fetch_bars.py \
    --symbol RELIANCE --interval 1d --days 365 [--provider kite]

Prints one JSON object to stdout with the resolved provider, symbol,
interval, bar count, first/last close, and the full serialized bar list.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.mechanics.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    NotConnectedError,
    RateLimitError,
)
from lib.mechanics.kite import fetch_kite_historical
from lib.mechanics.models import Bar
from lib.mechanics.state import load_credentials, load_most_recent
from lib.mechanics.store import DuckDBStore

_FETCH_BY_PROVIDER = {
    "kite": fetch_kite_historical,
}


def _resolve_provider(explicit_provider: str | None) -> tuple[str, dict[str, str]]:
    if explicit_provider:
        creds = load_credentials(explicit_provider)
        if creds is None:
            raise NotConnectedError(
                f"no stored session for provider {explicit_provider!r} - run "
                "the connect-adapter skill first."
            )
        return explicit_provider, creds
    most_recent = load_most_recent()
    if most_recent is None:
        raise NotConnectedError("no adapter is connected yet - run the connect-adapter skill first.")
    return most_recent


async def fetch_symbol_bars(
    store: DuckDBStore,
    provider: str,
    creds: dict[str, str],
    symbol: str,
    interval: str,
    frm: datetime,
    to: datetime,
) -> list[Bar]:
    """Fill any missing gap in the store, then return the full requested range."""
    fetch = _FETCH_BY_PROVIDER.get(provider)
    if fetch is None:
        raise DataUnavailableError(f"provider {provider!r} has no fetch mechanics wired up")

    for gap_from, gap_to in store.find_missing_range(symbol, interval, frm, to):
        fetched = await fetch(
            api_key=creds["api_key"],
            access_token=creds["access_token"],
            symbol=symbol,
            interval=interval,
            frm=gap_from,
            to=gap_to,
        )
        store.write_bars(fetched)

    bars = store.query_bars(symbol, interval, frm, to)
    if not bars:
        raise DataUnavailableError(
            f"no bars found for {symbol!r} in the requested range - try a different symbol or a wider range."
        )
    return bars


async def _run(symbol: str, interval: str, days: int, provider: str | None) -> dict[str, object]:
    resolved_provider, creds = _resolve_provider(provider)
    store = DuckDBStore()
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    try:
        bars = await fetch_symbol_bars(store, resolved_provider, creds, symbol, interval, frm, to)
    except AuthExpiredError:
        raise SystemExit(
            json.dumps(
                {
                    "error": f"the stored {resolved_provider} session has expired - reconnect via the connect-adapter skill."
                }
            )
        ) from None
    except RateLimitError as exc:
        raise SystemExit(
            json.dumps({"error": f"{resolved_provider} rate-limited the fetch call: {exc}. Wait a moment and retry."})
        ) from None

    return {
        "provider": resolved_provider,
        "symbol": symbol,
        "interval": interval,
        "bar_count": len(bars),
        "first_close": bars[0].close,
        "last_close": bars[-1].close,
        "bars": [asdict(b) | {"ts": b.ts.isoformat()} for b in bars],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(_run(args.symbol, args.interval, args.days, args.provider))
    except (NotConnectedError, DataUnavailableError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
