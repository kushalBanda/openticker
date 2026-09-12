#!/usr/bin/env python3
"""run-backtest skill script: run a strategy backtest over real bars.

Run as: uv run python plugin/skills/run-backtest/scripts/run_backtest.py \
    --strategy sma_cross --symbols RELIANCE \
    --params '{"long_window": 20, "quantity": 10}' \
    [--interval 1d] [--days 365] [--cash 100000] [--provider kite] \
    [--commission-per-share 0.0] [--slippage-bps 0.0] [--cost-profile kite_delivery]

Prints one JSON object: the backtest report, or {"error": "..."} on failure.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.cost_models import (
    groww_delivery_cost,
    groww_intraday_cost,
    kite_delivery_cost,
    kite_intraday_cost,
)
from lib.math.exceptions import InsufficientDataError
from lib.math.performance import compute_metrics
from lib.math.portfolio import Portfolio
from lib.math.strategies.buy_and_hold import make_buy_and_hold_on_bar
from lib.math.strategies.mean_reversion import make_mean_reversion_on_bar
from lib.math.strategies.pairs_trading import make_pairs_trading_on_bar
from lib.math.strategies.sma_cross import make_sma_cross_on_bar
from lib.math.strategies.time_series_momentum import (
    make_time_series_momentum_on_bar,
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

COST_PROFILE_FREE = "free"
COST_PROFILE_MANUAL = "manual"
COST_SEGMENT_DELIVERY = "delivery"
COST_SEGMENT_INTRADAY = "intraday"
DELIVERY_INTERVAL = "1d"

_STRATEGY_FACTORY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "sma_cross": make_sma_cross_on_bar,
    "buy_and_hold": make_buy_and_hold_on_bar,
    "mean_reversion": make_mean_reversion_on_bar,
    "pairs_trading": make_pairs_trading_on_bar,
    "time_series_momentum": make_time_series_momentum_on_bar,
}

_COST_PROFILES: dict[str, Callable[[int, float], float]] = {
    "kite_delivery": kite_delivery_cost,
    "kite_intraday": kite_intraday_cost,
    "groww_delivery": groww_delivery_cost,
    "groww_intraday": groww_intraday_cost,
}


def _resolve_cost_fn(
    cost_profile: str | None, resolved_provider: str, interval: str, commission_per_share: float
) -> tuple[Callable[[int, float], float], str, bool]:
    """Picks the cost function to charge fills with.

    Returns (cost_fn, profile actually used, whether it was auto-selected
    from the resolved adapter rather than named by the caller).
    """
    if cost_profile == COST_PROFILE_MANUAL:
        return lambda quantity, price: quantity * commission_per_share, COST_PROFILE_MANUAL, False
    if cost_profile == COST_PROFILE_FREE:
        return lambda quantity, price: 0.0, COST_PROFILE_FREE, False
    if cost_profile is not None:
        return _COST_PROFILES[cost_profile], cost_profile, False

    segment = COST_SEGMENT_DELIVERY if interval == DELIVERY_INTERVAL else COST_SEGMENT_INTRADAY
    auto_key = f"{resolved_provider}_{segment}"
    if auto_key in _COST_PROFILES:
        return _COST_PROFILES[auto_key], auto_key, True
    return lambda quantity, price: 0.0, COST_PROFILE_FREE, True


async def _run(
    strategy: str,
    symbols: list[str],
    params: dict[str, Any],
    interval: str,
    days: int,
    cash: float,
    provider: str | None,
    commission_per_share: float,
    slippage_bps: float,
    cost_profile: str | None,
) -> dict[str, Any]:
    make_on_bar = _STRATEGY_FACTORY.get(strategy)
    if make_on_bar is None:
        raise ValueError(f"no strategy named {strategy!r} - available: {sorted(_STRATEGY_FACTORY)}")
    on_bar = make_on_bar(params)

    resolved_provider, creds = _resolve_provider(provider)
    store = DuckDBStore()
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    bars_by_symbol: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars_by_symbol[symbol] = await fetch_symbol_bars(store, resolved_provider, creds, symbol, interval, frm, to)

    cost_fn, resolved_cost_profile, cost_profile_auto_selected = _resolve_cost_fn(
        cost_profile, resolved_provider, interval, commission_per_share
    )
    broker = BacktestBroker(cost_fn=cost_fn, slippage_bps=slippage_bps)
    portfolio = Portfolio(starting_cash=cash)
    portfolio = await run_backtest_loop(bars_by_symbol, on_bar, broker, portfolio)

    ending_equity = portfolio.equity_curve[-1][1] if portfolio.equity_curve else portfolio.cash
    total_commission_paid = sum(entry.commission for entry in portfolio.ledger.entries)

    result: dict[str, Any] = {
        "provider": resolved_provider,
        "strategy": strategy,
        "params": params,
        "symbols": symbols,
        "interval": interval,
        "days": days,
        "starting_cash": cash,
        "ending_cash": portfolio.cash,
        "ending_equity": ending_equity,
        "positions": portfolio.positions,
        "costs": {
            "profile": resolved_cost_profile,
            "auto_selected_from_adapter": cost_profile_auto_selected,
            "slippage_bps": slippage_bps,
            "total_commission_paid": total_commission_paid,
        },
    }

    try:
        report = compute_metrics(portfolio.equity_curve)
    except InsufficientDataError as exc:
        result["performance"] = None
        result["performance_note"] = (
            f"performance metrics unavailable: the fetched bars are too irregularly spaced to annualize ({exc})."
        )
    else:
        result["performance"] = {
            "total_return": report.total_return,
            "annualized_return": report.annualized_return,
            "max_drawdown": report.max_drawdown,
            "sharpe_ratio": report.sharpe_ratio,
            "exponential_std": report.exponential_std,
            "win_rate": report.win_rate,
        }

    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--commission-per-share", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument(
        "--cost-profile",
        choices=["kite_delivery", "kite_intraday", "groww_delivery", "groww_intraday", "free", "manual"],
        default=None,
    )
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(
            _run(
                args.strategy,
                args.symbols,
                json.loads(args.params),
                args.interval,
                args.days,
                args.cash,
                args.provider,
                args.commission_per_share,
                args.slippage_bps,
                args.cost_profile,
            )
        )
    except (
        ValueError,
        TypeError,
        NotConnectedError,
        AuthExpiredError,
        RateLimitError,
        DataUnavailableError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
