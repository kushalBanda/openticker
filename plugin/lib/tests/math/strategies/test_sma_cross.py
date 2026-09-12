from datetime import UTC, datetime, timedelta

import pytest

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.math.strategies.sma_cross import make_sma_cross_on_bar
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(symbol="X", interval="1d", ts=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1000, provider="kite")
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_enters_long_on_crossover_up() -> None:
    # Flat prices below a rising SMA, then a sharp jump crosses price above it.
    closes = [100.0] * 5 + [150.0] * 5
    bars = {"X": _bars(closes)}
    on_bar = make_sma_cross_on_bar({"long_window": 5, "quantity": 10})
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = BacktestBroker()

    await run_backtest_loop(bars, on_bar, broker, portfolio)

    assert len(portfolio.ledger.entries) >= 1
    assert portfolio.ledger.entries[0].side == "buy"
