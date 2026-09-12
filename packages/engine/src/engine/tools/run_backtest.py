"""run_backtest MCP tool (quant-engine server): run a registered strategy over real bars."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from ingest.core.models import Bar
from pydantic import Field
from quant.core.exceptions import InsufficientDataError
from strategy.backtest.broker import BacktestBroker
from strategy.core.cost_model import (
    BpsSlippageModel,
    PerShareFeeModel,
    TransactionCostModel,
    groww_delivery_cost_model,
    groww_intraday_cost_model,
    kite_delivery_cost_model,
    kite_intraday_cost_model,
)
from strategy.core.engine import BacktestEngine
from strategy.core.exceptions import UnknownStrategyError
from strategy.core.portfolio import Portfolio
from strategy.core.registry import StrategyFactory, list_strategy_names
from strategy.metrics.performance import compute_metrics

from engine.core.constants import (
    COST_PROFILE_FREE,
    COST_PROFILE_MANUAL,
    COST_SEGMENT_DELIVERY,
    COST_SEGMENT_INTRADAY,
    DELIVERY_INTERVAL,
)
from engine.core.data import connect_engine, fetch_symbol_bars
from engine.core.exceptions import InvalidStrategyParamsError
from engine.core.serialization import to_json_dict
from engine.core.strategies import ensure_strategies_registered

_COST_PROFILES: dict[str, TransactionCostModel] = {
    "kite_delivery": kite_delivery_cost_model(),
    "kite_intraday": kite_intraday_cost_model(),
    "groww_delivery": groww_delivery_cost_model(),
    "groww_intraday": groww_intraday_cost_model(),
}


def _resolve_cost_model(
    cost_profile: str | None,
    resolved_provider: str,
    interval: str,
    commission_per_share: float,
) -> tuple[TransactionCostModel, str, bool]:
    """Picks the cost model to charge fills with.

    Returns (model, profile actually used, whether it was auto-selected
    from the resolved adapter rather than named by the caller).
    """
    if cost_profile == COST_PROFILE_MANUAL:
        return PerShareFeeModel(commission_per_share), COST_PROFILE_MANUAL, False
    if cost_profile == COST_PROFILE_FREE:
        return PerShareFeeModel(0.0), COST_PROFILE_FREE, False
    if cost_profile is not None:
        return _COST_PROFILES[cost_profile], cost_profile, False

    # No explicit choice: charge whatever the connected adapter actually
    # charges, so a caller who never thinks about costs still gets a
    # realistic result instead of a silently frictionless one.
    segment = COST_SEGMENT_DELIVERY if interval == DELIVERY_INTERVAL else COST_SEGMENT_INTRADAY
    auto_key = f"{resolved_provider}_{segment}"
    if auto_key in _COST_PROFILES:
        return _COST_PROFILES[auto_key], auto_key, True
    return PerShareFeeModel(0.0), COST_PROFILE_FREE, True


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
    commission_per_share: Annotated[
        float,
        Field(
            description=(
                'Flat commission per share, only used when cost_profile="manual" '
                "(otherwise ignored in favor of the resolved adapter's real "
                "schedule, or whatever cost_profile names). Default 0.0."
            ),
            ge=0,
        ),
    ] = 0.0,
    slippage_bps: Annotated[
        float,
        Field(
            description=(
                "Price-impact slippage in basis points applied against the "
                "trader on every fill (a buy pays more, a sell receives "
                "less), e.g. 10.0 for 0.1%. Default 0.0 (no slippage, "
                "unrealistic for most instruments)."
            ),
            ge=0,
        ),
    ] = 0.0,
    cost_profile: Annotated[
        Literal[
            "kite_delivery",
            "kite_intraday",
            "groww_delivery",
            "groww_intraday",
            "free",
            "manual",
        ]
        | None,
        Field(
            description=(
                "Which broker fee schedule to charge fills with. Omit (default) "
                "to auto-select the resolved adapter's real schedule - "
                '"kite_delivery"/"groww_delivery" when interval="1d", '
                '"kite_intraday"/"groww_intraday" otherwise - so results reflect '
                "what that adapter actually charges without the caller having "
                'to know it. Pass "kite_delivery" (Zerodha, Rs 0 brokerage but '
                "STT/exchange/SEBI/stamp-duty/GST still apply), \"kite_intraday\" "
                '(brokerage capped at min(0.03%, Rs 20/order)), "groww_delivery" '
                "(brokerage capped at min(0.1%, Rs 20/order) plus a flat Rs 16.5 "
                'DP charge, Groww dropped free delivery in 2024), or '
                '"groww_intraday" (brokerage capped at min(0.1%, Rs 20/order)) '
                'to force a specific schedule regardless of adapter. Pass "free" '
                'for zero-cost frictionless fills, or "manual" to use '
                "commission_per_share as a flat per-share fee instead. "
                "slippage_bps always applies separately (these schedules model "
                "brokerage/statutory charges, not market impact)."
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

    cost_model, resolved_cost_profile, cost_profile_auto_selected = _resolve_cost_model(
        cost_profile, resolved_provider, interval, commission_per_share
    )
    backtest_engine = BacktestEngine(
        broker=BacktestBroker(
            cost_model=cost_model,
            slippage_model=BpsSlippageModel(slippage_bps),
        ),
        portfolio=Portfolio(starting_cash=cash),
    )
    portfolio = await backtest_engine.run(bars_by_symbol, strategy_instance)

    # equity_curve's last point is cash + mark-to-market position value
    # (Portfolio.mark_to_market) - the true ending value, not just cash.
    # Falls back to cash only if the curve is empty (no bars ever marked).
    ending_equity = portfolio.equity_curve[-1][1] if portfolio.equity_curve else portfolio.cash
    total_commission_paid = sum(entry.commission for entry in portfolio.ledger.entries)

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
        # Reported separately from cash/equity above (which already have
        # these costs baked in through each fill) so a caller can see the
        # cost impact on its own, not just infer it from a lower ending
        # number - and see which schedule was applied without guessing.
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
            f"performance metrics unavailable: the fetched bars are too "
            f"irregularly spaced to annualize ({exc}). This is a known "
            "packages/ingest data-completeness gap, not a strategy error."
        )
    else:
        result["performance"] = to_json_dict(report)

    return result
