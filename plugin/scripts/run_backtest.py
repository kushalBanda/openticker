"""Run a backtest for a registered strategy against real historical bars.

The strategy/quant counterpart to fetch_bars.py: fetches bars for one or
more symbols through the connected adapter, runs a chosen strategy over
them via the hand-built backtest engine (packages/strategy), and prints
the resulting performance report. No server call is involved.

Run with:
  uv run python plugin/scripts/run_backtest.py \\
      --strategy sma_cross --symbols RELIANCE --days 365 \\
      --param long_window=20 --param quantity=10

See plugin/references/strategies.md for each strategy's required params.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategies import ensure_strategies_registered

from data import connect_engine, fetch_symbol_bars


def _parse_params(raw: list[str]) -> dict[str, float | int]:
    params: dict[str, float | int] = {}
    for item in raw:
        if "=" not in item:
            raise SystemExit(f"--param {item!r} is not in key=value form")
        key, _, value = item.partition("=")
        try:
            params[key] = int(value)
        except ValueError:
            try:
                params[key] = float(value)
            except ValueError:
                raise SystemExit(f"--param {item!r}: value must be a number") from None
    return params


async def _run(
    strategy_name: str,
    symbols: list[str],
    interval: str,
    days: int,
    cash: float,
    provider: str | None,
    params: dict[str, float | int],
) -> None:
    from strategy.backtest.broker import BacktestBroker
    from strategy.core.engine import BacktestEngine
    from strategy.core.exceptions import UnknownStrategyError
    from strategy.core.portfolio import Portfolio
    from strategy.core.registry import StrategyFactory, list_strategy_names
    from strategy.metrics.performance import compute_metrics

    ensure_strategies_registered()
    try:
        strategy = StrategyFactory.create(strategy_name, params)
    except UnknownStrategyError:
        names = ", ".join(list_strategy_names())
        raise SystemExit(
            f"no strategy named {strategy_name!r} - available: {names}"
        ) from None
    except TypeError as exc:
        raise SystemExit(
            f"bad --param for strategy {strategy_name!r}: {exc}. See "
            "plugin/references/strategies.md for its required params."
        ) from None

    resolved_provider, engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    from ingest.core.models import Bar

    bars: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars[symbol] = await fetch_symbol_bars(engine, resolved_provider, symbol, interval, frm, to)

    from quant.core.exceptions import InsufficientDataError

    backtest_engine = BacktestEngine(broker=BacktestBroker(), portfolio=Portfolio(starting_cash=cash))
    portfolio = await backtest_engine.run(bars, strategy)

    print(f"provider: {resolved_provider}")
    print(f"strategy: {strategy_name}  params: {params}")
    print(f"symbols: {', '.join(symbols)}  interval: {interval}  days: {days}")
    print(f"starting cash: {cash:,.2f}")
    print()

    try:
        report = compute_metrics(portfolio.equity_curve)
    except InsufficientDataError as exc:
        print(
            "performance metrics unavailable: the fetched bars are too "
            f"irregularly spaced to annualize ({exc}). This is a known "
            "packages/ingest data-completeness gap, not a strategy error."
        )
        curve = portfolio.equity_curve
        if curve:
            start_ts, start_value = curve[0]
            end_ts, end_value = curve[-1]
            raw_return = (end_value - start_value) / start_value if start_value else 0.0
            print(f"raw equity: {start_ts.date()} {start_value:,.2f} -> {end_ts.date()} {end_value:,.2f}")
            print(f"raw return (not annualized): {raw_return:+.2%}")
    else:
        print(f"total return:       {report.total_return:+.2%}")
        print(f"annualized return:  {report.annualized_return:+.2%}")
        print(f"max drawdown:       {report.max_drawdown:.2%}")
        print(f"sharpe ratio:       {report.sharpe_ratio:.2f}")
        print(f"win rate:           {report.win_rate:.2%}")

    print()
    print(f"ending cash: {portfolio.cash:,.2f}   positions: {portfolio.positions}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, help="registered strategy name, e.g. sma_cross")
    parser.add_argument(
        "--symbols", required=True, help="comma-separated tradingsymbols, e.g. RELIANCE,TCS"
    )
    parser.add_argument("--days", type=int, default=365, help="lookback window in days")
    parser.add_argument("--interval", default="1d", help="canonical interval, e.g. 1d, 1m")
    parser.add_argument("--cash", type=float, default=100_000.0, help="starting cash")
    parser.add_argument(
        "--provider",
        default=None,
        help="which connected provider to use (default: most recently connected)",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="key=value",
        help="a strategy constructor param, repeatable - see references/strategies.md",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("--symbols must list at least one tradingsymbol")
    params = _parse_params(args.param)

    asyncio.run(
        _run(args.strategy, symbols, args.interval, args.days, args.cash, args.provider, params)
    )


if __name__ == "__main__":
    main()
