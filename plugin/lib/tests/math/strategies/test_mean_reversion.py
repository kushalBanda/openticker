from datetime import UTC, datetime, timedelta

import pytest

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.math.strategies.mean_reversion import make_mean_reversion_on_bar
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(symbol="X", interval="1d", ts=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1000, provider="kite")
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_enters_long_on_oversold_dip_below_lower_band() -> None:
    # Mildly oscillating baseline (never perfectly flat - a zero-variance
    # window degenerates RSI to exactly 100 via the avg_loss==0 branch,
    # an edge case real market data never hits), then a sharp one-bar
    # drop pushes price below the lower Bollinger band while RSI reads
    # oversold.
    baseline = [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(20)]
    closes = baseline + [70.0, 70.0]  # one extra bar so the fill has a next bar to land on
    bars = {"X": _bars(closes)}
    on_bar = make_mean_reversion_on_bar(
        {"bb_window": 20, "bb_std": 2.0, "rsi_period": 14, "rsi_buy_threshold": 30.0, "rsi_sell_threshold": 70.0, "quantity": 10}
    )
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = BacktestBroker()

    await run_backtest_loop(bars, on_bar, broker, portfolio)

    assert len(portfolio.ledger.entries) >= 1
    assert portfolio.ledger.entries[0].side == "buy"
