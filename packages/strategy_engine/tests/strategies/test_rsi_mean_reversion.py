from datetime import UTC, datetime, timedelta

from data_engine.core.models import Bar
from strategy_engine.backtest.broker import BacktestBroker
from strategy_engine.core.engine import BacktestEngine
from strategy_engine.core.portfolio import Portfolio
from strategy_engine.strategies.rsi_mean_reversion.strategy import (
    RsiMeanReversionStrategy,
)


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


def test_generates_buy_signal_when_oversold() -> None:
    # A sustained decline drives average loss well above average gain,
    # pushing RSI below the oversold threshold.
    closes = [100.0 - i for i in range(20)]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = RsiMeanReversionStrategy(
        period=14, oversold=30.0, overbought=70.0, quantity=5
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 5
