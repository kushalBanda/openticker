"""run_backtest MCP tool (quant-engine server): run a registered strategy over real bars."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from ingest.core.models import Bar
from pydantic import Field
from quant.core.exceptions import InsufficientDataError
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.exceptions import UnknownStrategyError
from strategy.core.portfolio import Portfolio
from strategy.core.registry import StrategyFactory, list_strategy_names
from strategy.metrics.performance import compute_metrics

from engine.core.data import connect_engine, fetch_symbol_bars
from engine.core.exceptions import InvalidStrategyParamsError
from engine.core.serialization import to_json_dict
from engine.core.strategies import ensure_strategies_registered


async def run_backtest(
    strategy: Annotated[
        str,
        Field(
            description=(
                'Registered strategy name, e.g. "sma_cross", "buy_and_hold", '
                '"mean_reversion", "pairs_trading", "time_series_momentum" - see '
                "plugin/references/strategies.md for each one's required params."
            )
        ),
    ],
    symbols: Annotated[
        list[str],
        Field(
            description=(
                "Tradingsymbols to fetch and trade, e.g. [\"RELIANCE\"]. "
                '"pairs_trading" and "time_series_momentum" need more than one '
                "symbol to be meaningful."
            )
        ),
    ],
    params: Annotated[
        dict[str, float | int] | None,
        Field(
            description=(
                "Constructor kwargs for the chosen strategy, e.g. "
                '{"long_window": 20, "quantity": 10} for "sma_cross". Omit or pass '
                "{} for strategies with no required params."
            )
        ),
    ] = None,
    interval: Annotated[
        str, Field(description='Canonical bar interval, e.g. "1d".')
    ] = "1d",
    days: Annotated[
        int, Field(description="Lookback window in days from now.", gt=0)
    ] = 365,
    cash: Annotated[
        float, Field(description="Starting portfolio cash.", gt=0)
    ] = 100_000.0,
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
    """Fetch bars for one or more symbols and run a strategy backtest.

    Returns:
        A dict with the resolved provider, strategy/params, a performance
        report (or a note that metrics are degraded), ending cash, ending
        equity (cash plus the mark-to-market value of open positions - the
        number that actually reflects the strategy's result, since ending
        cash alone reads as a loss whenever the strategy still holds an
        open position), and open positions.

    Raises:
        engine.core.exceptions.NotConnectedError: No adapter is connected.
        engine.core.exceptions.SessionExpiredError: The stored session expired.
        engine.core.exceptions.ProviderRateLimitedError: The provider
            rejected a connect/fetch call for exceeding its rate limit.
        engine.core.exceptions.InvalidStrategyParamsError: params don't
            match the strategy's constructor.
        strategy.core.exceptions.UnknownStrategyError: Unregistered
            strategy name (message lists the available strategies).
    """
    ensure_strategies_registered()
    resolved_params = params or {}
    try:
        strategy_instance = StrategyFactory.create(strategy, resolved_params)
    except UnknownStrategyError:
        names = ", ".join(list_strategy_names())
        raise UnknownStrategyError(
            f"no strategy named {strategy!r} - available: {names}"
        ) from None
    except TypeError as exc:
        raise InvalidStrategyParamsError(
            f"bad params for strategy {strategy!r}: {exc}. See "
            "plugin/references/strategies.md for its required params."
        ) from None

    resolved_provider, data_engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)

    bars_by_symbol: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars_by_symbol[symbol] = await fetch_symbol_bars(
            data_engine, resolved_provider, symbol, interval, frm, to
        )

    backtest_engine = BacktestEngine(broker=BacktestBroker(), portfolio=Portfolio(starting_cash=cash))
    portfolio = await backtest_engine.run(bars_by_symbol, strategy_instance)

    # equity_curve's last point is cash + mark-to-market position value
    # (Portfolio.mark_to_market) - the true ending value, not just cash.
    # Falls back to cash only if the curve is empty (no bars ever marked).
    ending_equity = portfolio.equity_curve[-1][1] if portfolio.equity_curve else portfolio.cash

    result: dict[str, Any] = {
        "provider": resolved_provider,
        "strategy": strategy,
        "params": resolved_params,
        "symbols": symbols,
        "interval": interval,
        "days": days,
        "starting_cash": cash,
        "ending_cash": portfolio.cash,
        "ending_equity": ending_equity,
        "positions": portfolio.positions,
    }

    try:
        report = compute_metrics(portfolio.equity_curve)
    except InsufficientDataError as exc:
        result["performance"] = None
        result["performance_note"] = (
            f"performance metrics unavailable: the fetched bars are too "
            f"irregularly spaced to annualize ({exc}). This is a known "
            "packages/ingest data-completeness gap, not a strategy error."
        )
    else:
        result["performance"] = to_json_dict(report)

    return result
