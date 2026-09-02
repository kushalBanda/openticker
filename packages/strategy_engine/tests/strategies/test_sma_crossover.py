from datetime import UTC, datetime, timedelta

from data_engine.core.models import Bar
from strategy_engine.backtest.broker import BacktestBroker
from strategy_engine.core.engine import BacktestEngine
from strategy_engine.core.portfolio import Portfolio
from strategy_engine.strategies.sma_crossover.strategy import SmaCrossoverStrategy


def _bar(day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


def test_generates_buy_signal_on_golden_cross() -> None:
    # Flat prices establish both SMAs equal (short below/equal long), then a
    # sharp rise pulls the short SMA above the long SMA, a golden cross.
    closes = [100.0] * 20 + [110.0, 120.0, 130.0, 140.0, 150.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = SmaCrossoverStrategy(short_window=5, long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10
