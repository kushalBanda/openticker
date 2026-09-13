#!/usr/bin/env python3
"""position-sizing skill script: a suggested stop, target, and quantity
for one symbol, given capital and a risk-per-trade percentage.

Run as: uv run python plugin/skills/position-sizing/scripts/position_sizing.py \
    --symbol RELIANCE --capital 200000 --risk-pct 1 [--reward-risk-ratio 2] \
    [--interval 1d] [--days 30] [--provider kite]

Prints one JSON object: entry_price, stop_distance, stop_price,
take_profit, quantity, or {"error": "..."} on failure. This script
suggests numbers - it does not decide whether to take the trade.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.math.exceptions import InsufficientDataError
from lib.math.position_sizing import (
    suggest_position_size,
    suggest_stop_distance,
    suggest_take_profit,
)
from lib.mechanics.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    NotConnectedError,
    RateLimitError,
)
from lib.mechanics.models import Bar
from lib.mechanics.store import DuckDBStore

sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "fetch-bars" / "scripts"))
from fetch_bars import _resolve_provider, fetch_symbol_bars


def build_sizing_json(
    bars: list[Bar], capital: float, risk_per_trade_pct: float, reward_risk_ratio: float
) -> dict[str, object]:
    entry_price = bars[-1].close
    stop_distance = suggest_stop_distance(bars)
    stop_price = entry_price - stop_distance
    take_profit = suggest_take_profit(entry_price, stop_distance, reward_risk_ratio)
    quantity = suggest_position_size(capital, risk_per_trade_pct, stop_distance, entry_price)
    return {
        "entry_price": entry_price,
        "stop_distance": stop_distance,
        "stop_price": stop_price,
        "take_profit": take_profit,
        "quantity": quantity,
    }


async def _run(
    symbol: str, capital: float, risk_per_trade_pct: float, reward_risk_ratio: float,
    interval: str, days: int, provider: str | None,
) -> dict[str, object]:
    resolved_provider, creds = _resolve_provider(provider)
    store = DuckDBStore()
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    bars = await fetch_symbol_bars(store, resolved_provider, creds, symbol, interval, frm, to)

    try:
        sizing = build_sizing_json(bars, capital, risk_per_trade_pct, reward_risk_ratio)
    except (InsufficientDataError, ValueError) as exc:
        raise SystemExit(json.dumps({"error": f"cannot size a trade on {symbol}: {exc}"})) from None

    return {"symbol": symbol, **sizing}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--risk-pct", type=float, required=True, dest="risk_per_trade_pct")
    parser.add_argument("--reward-risk-ratio", type=float, default=2.0)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(
            _run(
                args.symbol, args.capital, args.risk_per_trade_pct, args.reward_risk_ratio,
                args.interval, args.days, args.provider,
            )
        )
    except (NotConnectedError, DataUnavailableError, AuthExpiredError, RateLimitError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
