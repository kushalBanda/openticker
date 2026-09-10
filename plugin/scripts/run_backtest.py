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
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Sibling scripts (data.py, strategies.py) are not an installed package,
# so importing them by name requires this directory on sys.path first -
# this must run before the sibling imports below, unlike every other
# import in this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from strategies import ensure_strategies_registered
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.exceptions import UnknownStrategyError
from strategy.core.interfaces import Strategy
from strategy.core.portfolio import Portfolio
from strategy.core.registry import StrategyFactory, list_strategy_names
from strategy.metrics.performance import PerformanceReport, compute_metrics
from strategy.storage.equity_curve_store import EquityCurveStore
from strategy.storage.ledger_store import LedgerStore
from strategy.storage.run_store import RunMetadata, RunStore

from data import connect_engine, fetch_symbol_bars


def _parse_params(raw: list[str]) -> dict[str, float | int]:
    """Parse repeated --param key=value flags into a strategy config dict.

    Args:
        raw: Raw "key=value" strings from argparse's action="append".

    Returns:
        Each value cast to int if possible, else float.

    Raises:
        SystemExit: A flag is not in key=value form, or its value isn't numeric.
    """
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


def _build_strategy(strategy_name: str, params: dict[str, float | int]) -> Strategy:
    """Build a registered strategy instance, translating bad input to SystemExit.

    Args:
        strategy_name: A name registered via @register_strategy.
        params: Constructor kwargs for that strategy.

    Returns:
        The constructed strategy instance.

    Raises:
        SystemExit: The strategy name is unknown, or params don't match
            its constructor.
    """
    ensure_strategies_registered()
    try:
        return StrategyFactory.create(strategy_name, params)
    except UnknownStrategyError:
        names = ", ".join(list_strategy_names())
        raise SystemExit(f"no strategy named {strategy_name!r} - available: {names}") from None
    except TypeError as exc:
        raise SystemExit(
            f"bad --param for strategy {strategy_name!r}: {exc}. See "
            "plugin/references/strategies.md for its required params."
        ) from None


def _print_report(report: PerformanceReport) -> None:
    """Print a PerformanceReport's fields as labeled, formatted lines."""
    print(f"total return:       {report.total_return:+.2%}")
    print(f"annualized return:  {report.annualized_return:+.2%}")
    print(f"max drawdown:       {report.max_drawdown:.2%}")
    print(f"sharpe ratio:       {report.sharpe_ratio:.2f}")
    print(f"win rate:           {report.win_rate:.2%}")


def _print_degraded_metrics(portfolio: Portfolio, exc: InsufficientDataError) -> None:
    """Print raw, non-annualized equity change when Sharpe/annualization can't be computed.

    Args:
        portfolio: The finished backtest's portfolio.
        exc: The InsufficientDataError compute_metrics raised.
    """
    print(
        "performance metrics unavailable: the fetched bars are too "
        f"irregularly spaced to annualize ({exc}). This is a known "
        "packages/ingest data-completeness gap, not a strategy error."
    )
    curve = portfolio.equity_curve
    if not curve:
        return
    start_ts, start_value = curve[0]
    end_ts, end_value = curve[-1]
    raw_return = (end_value - start_value) / start_value if start_value else 0.0
    print(f"raw equity: {start_ts.date()} {start_value:,.2f} -> {end_ts.date()} {end_value:,.2f}")
    print(f"raw return (not annualized): {raw_return:+.2%}")


def _persist_run(
    strategy_name: str,
    params: dict[str, float | int],
    symbols: list[str],
    interval: str,
    cash: float,
    portfolio: Portfolio,
) -> str | None:
    """Persist a finished run's metadata, ledger, and equity curve for later visualization.

    Args:
        strategy_name: The strategy that was run.
        params: Its constructor params.
        symbols: Symbols traded.
        interval: Bar interval used.
        cash: Starting cash.
        portfolio: The finished backtest's portfolio.

    Returns:
        The generated run id, or None if persistence failed. A warning is
        printed to stderr in that case; the caller's performance report has
        already printed successfully and must not be treated as failed.
    """
    run_id = f"{strategy_name}_{datetime.now(UTC):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
    try:
        RunStore().write_run(
            RunMetadata(
                run_id=run_id,
                created_at=datetime.now(UTC),
                strategy=strategy_name,
                params=params,
                symbols=symbols,
                interval=interval,
                starting_cash=cash,
            )
        )
        LedgerStore().write_entries(run_id, portfolio.ledger.entries)
        EquityCurveStore().write_points(run_id, portfolio.equity_curve)
    except Exception as exc:  # noqa: BLE001 - persistence must never fail an already-printed report
        print(f"warning: could not save this run for later visualization: {exc}", file=sys.stderr)
        return None
    return run_id


async def _run(
    strategy_name: str,
    symbols: list[str],
    interval: str,
    days: int,
    cash: float,
    provider: str | None,
    params: dict[str, float | int],
) -> None:
    """Fetch bars, run the backtest, and print the resulting report.

    Args:
        strategy_name: A name registered via @register_strategy.
        symbols: Tradingsymbols to fetch and trade.
        interval: Canonical bar interval, e.g. "1d".
        days: Lookback window in days from now.
        cash: Starting portfolio cash.
        provider: A provider name to use, or None for the most recently
            connected one.
        params: Constructor kwargs for the chosen strategy.
    """
    strategy = _build_strategy(strategy_name, params)

    resolved_provider, engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    bars: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars[symbol] = await fetch_symbol_bars(engine, resolved_provider, symbol, interval, frm, to)

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
        _print_degraded_metrics(portfolio, exc)
    else:
        _print_report(report)

    print()
    print(f"ending cash: {portfolio.cash:,.2f}   positions: {portfolio.positions}")

    run_id = _persist_run(strategy_name, params, symbols, interval, cash, portfolio)
    if run_id is not None:
        print(f"run id: {run_id}  (visualize with: uv run python plugin/scripts/visualize_backtest.py --run {run_id})")


def _parse_args() -> argparse.Namespace:
    """Define and parse this script's CLI arguments."""
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
    return parser.parse_args()


def main() -> None:
    """Parse CLI arguments and run the backtest."""
    args = _parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("--symbols must list at least one tradingsymbol")
    params = _parse_params(args.param)

    asyncio.run(
        _run(args.strategy, symbols, args.interval, args.days, args.cash, args.provider, params)
    )


if __name__ == "__main__":
    main()
