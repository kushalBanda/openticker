"""The bar-by-bar backtest loop.

Ported from strategy.core.engine.BacktestEngine, flattened from a class
into one function. Orders placed on bar i fill on bar i+1, never
same-bar - do not change this ordering without understanding it
introduces lookahead bias.
"""

import logging
from collections.abc import Awaitable, Callable

from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.mechanics.models import Bar

logger = logging.getLogger(__name__)

OnBar = Callable[[dict[str, Bar], Portfolio, BacktestBroker], Awaitable[None]]


def _build_timestep_batches(bars: dict[str, list[Bar]]) -> list[dict[str, Bar]]:
    timestamps = sorted({bar.ts for symbol_bars in bars.values() for bar in symbol_bars})
    bars_by_symbol_ts = {
        (bar.ts, symbol): bar for symbol, symbol_bars in bars.items() for bar in symbol_bars
    }
    return [
        {
            symbol: bars_by_symbol_ts[(ts, symbol)]
            for symbol in bars
            if (ts, symbol) in bars_by_symbol_ts
        }
        for ts in timestamps
    ]


async def run_backtest_loop(
    bars: dict[str, list[Bar]],
    on_bar: OnBar,
    broker: BacktestBroker,
    portfolio: Portfolio,
) -> Portfolio:
    """Walks every symbol's bars in timestamp order, calling on_bar for
    each batch, then filling any pending orders against the next batch,
    then marking the portfolio to market on the current batch.
    """
    batches = _build_timestep_batches(bars)
    for i, batch in enumerate(batches):
        await on_bar(batch, portfolio, broker)
        if i + 1 < len(batches):
            fills = await broker.match_pending_orders(batches[i + 1])
            portfolio.apply_fills(fills)
        portfolio.mark_to_market(batch)

    dropped = await broker.close()
    if dropped:
        logger.warning(
            "%d order(s) placed on the last bar had no next bar to fill against, dropped: %s",
            len(dropped),
            dropped,
        )
    return portfolio
