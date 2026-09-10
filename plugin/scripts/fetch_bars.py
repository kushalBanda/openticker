"""Fetch historical bars for a symbol through a connected adapter.

The minimal, data-only slice of the research agent (docs/v2/quant-plugin/
issues/05-research-agent-v1.md) - bars only, no report writing, no web
enrichment. Built so "fetch me <symbol> data for the last year" is
testable today, before the fuller research skill exists.

Run with: uv run python plugin/scripts/fetch_bars.py SYMBOL [--days N] [--interval 1d]
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import connect_engine, fetch_symbol_bars


async def _fetch(symbol: str, interval: str, days: int, provider: str | None) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="tradingsymbol, e.g. RELIANCE")
    parser.add_argument("--days", type=int, default=365, help="lookback window in days")
    parser.add_argument("--interval", default="1d", help="canonical interval, e.g. 1d, 1m")
    parser.add_argument(
        "--provider",
        default=None,
        help="which connected provider to use (default: most recently connected)",
    )
    args = parser.parse_args()

    import asyncio

    asyncio.run(_fetch(args.symbol, args.interval, args.days, args.provider))


if __name__ == "__main__":
    main()
