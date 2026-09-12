from datetime import UTC, datetime, timedelta

import pytest

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.math.strategies.time_series_momentum import make_time_series_momentum_on_bar
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(symbol="X", interval="1d", ts=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1000, provider="kite")
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_goes_long_on_positive_trailing_return() -> None:
    # A steady uptrend over more than window+1 bars, spanning a calendar
    # month boundary so the monthly rebalance actually fires.
    closes = [100.0 + i * 0.5 for i in range(35)]
    bars = {"X": _bars(closes)}
    on_bar = make_time_series_momentum_on_bar({"window": 20, "target_risk_pct": 0.1, "vol_window": 10})
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = BacktestBroker()

    await run_backtest_loop(bars, on_bar, broker, portfolio)

    assert len(portfolio.ledger.entries) >= 1
    assert portfolio.ledger.entries[0].side == "buy"
