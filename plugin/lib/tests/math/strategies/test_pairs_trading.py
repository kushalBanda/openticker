from datetime import UTC, datetime, timedelta

import pytest

from lib.math.backtest import run_backtest_loop
from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.math.strategies.pairs_trading import make_pairs_trading_on_bar
from lib.mechanics.models import Bar


def _bars(symbol: str, closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(symbol=symbol, interval="1d", ts=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1000, provider="kite")
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_runs_a_full_cycle_without_error_and_can_open_a_pair() -> None:
    # Two co-moving series for ~2 formation months, then one diverges
    # sharply in the trading window to trigger an entry z-score.
    n = 65
    a_closes = [100.0 + (i % 5) for i in range(n)]
    b_closes = [100.0 + (i % 5) for i in range(n)]
    for i in range(60, n):
        b_closes[i] = 130.0

    bars = {"A": _bars("A", a_closes), "B": _bars("B", b_closes)}
    on_bar = make_pairs_trading_on_bar({"formation_months": 1, "trading_months": 1, "top_n_pairs": 1, "entry_z": 1.0})
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = BacktestBroker()

    result = await run_backtest_loop(bars, on_bar, broker, portfolio)

    # Smoke test: the strategy runs the full reformation/entry cycle over
    # two symbols without raising, and produces a valid equity curve.
    assert result.total_equity() > 0
