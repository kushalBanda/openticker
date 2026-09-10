"""Fetch historical bars for a symbol through a connected adapter.

The minimal, data-only slice of the research agent (docs/v2/quant-plugin/
issues/05-research-agent-v1.md) - bars only, no report writing, no web
enrichment. Built so "fetch me <symbol> data for the last year" is
testable today, before the fuller research skill exists.

Run with: uv run python plugin/scripts/fetch_bars.py SYMBOL [--days N] [--interval 1d]
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# data.py is a sibling script, not an installed package, so importing it
# by name requires this directory on sys.path first.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import connect_engine, fetch_symbol_bars


async def _fetch(symbol: str, interval: str, days: int, provider: str | None) -> None:
    """Fetch and print OHLCV bars for one symbol.

    Args:
        symbol: Tradingsymbol to fetch, e.g. "RELIANCE".
        interval: Canonical bar interval, e.g. "1d".
        days: Lookback window in days from now.
        provider: A provider name to use, or None for the most recently
            connected one.
    """
    resolved_provider, engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    bars = await fetch_symbol_bars(engine, resolved_provider, symbol, interval, frm, to)

    closes = [b.close for b in bars]
    print(f"provider: {resolved_provider}")
    print(f"symbol: {symbol}  interval: {interval}  bars: {len(bars)}")
    print(f"range: {bars[0].ts.date()} to {bars[-1].ts.date()}")
    print(f"first close: {bars[0].close}   last close: {bars[-1].close}")
    print(f"min close: {min(closes)}   max close: {max(closes)}")
    pct_change = (bars[-1].close - bars[0].close) / bars[0].close * 100
    print(f"change over range: {pct_change:+.2f}%")

    print()
    print("date        open      high      low       close     volume")
    for b in bars:
        print(
            f"{b.ts.date()}  {b.open:>8.2f}  {b.high:>8.2f}  "
            f"{b.low:>8.2f}  {b.close:>8.2f}  {b.volume:>10d}"
        )


def _parse_args() -> argparse.Namespace:
    """Define and parse this script's CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="tradingsymbol, e.g. RELIANCE")
    parser.add_argument("--days", type=int, default=365, help="lookback window in days")
    parser.add_argument("--interval", default="1d", help="canonical interval, e.g. 1d, 1m")
    parser.add_argument(
        "--provider",
        default=None,
        help="which connected provider to use (default: most recently connected)",
    )
    return parser.parse_args()


def main() -> None:
    """Parse CLI arguments and fetch bars."""
    args = _parse_args()
    asyncio.run(_fetch(args.symbol, args.interval, args.days, args.provider))


if __name__ == "__main__":
    main()
