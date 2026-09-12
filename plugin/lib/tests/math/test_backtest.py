from datetime import UTC, datetime, timedelta

import pytest

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.models import Order
from lib.math.portfolio import Portfolio
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="X", interval="1d", ts=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000, provider="kite",
        )
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_order_placed_on_bar_i_fills_on_bar_i_plus_1() -> None:
    bars = {"X": _bars([100.0, 101.0, 102.0])}
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    placed_on_first_bar_only = {"done": False}

    async def on_bar(batch, portfolio, broker):  # type: ignore[no-untyped-def]
        if not placed_on_first_bar_only["done"]:
            placed_on_first_bar_only["done"] = True
            order = Order(
                symbol="X", side="buy", quantity=1, order_type="market",
                placed_at_ts=next(iter(batch.values())).ts,
            )
            await broker.submit_order(order)

    await run_backtest_loop(bars, on_bar, broker, portfolio)

    assert len(portfolio.ledger.entries) == 1
    entry = portfolio.ledger.entries[0]
    # Fill happened at bar index 1's open (101.0), not bar index 0's.
    assert entry.fill_price == 101.0
